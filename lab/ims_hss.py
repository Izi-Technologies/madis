#!/usr/bin/env python3
"""Bounded lab HSS/UDM adapter for Madis IMS interoperability work.

The service has two deliberately small interfaces:

* a Diameter TCP/TLS listener for Cx UAR, SAR, LIR, and MAR requests;
* an HTTPS/HTTP JSON endpoint implementing the Madis subscriber authorization
  contract.

This is a lab adapter.  It does not implement Milenage/TUAK, a complete HSS
database, Sh user-data semantics, Diameter relay behavior, or carrier policy.
The configured XRES values are test credentials and are never returned by the
HTTP authorization endpoint.  Keep the listeners private and use TLS plus
operator-managed credentials outside local-only tests.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
import secrets
import socket
import ssl
import struct
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable


MAX_DIAMETER = 1 << 20
MAX_HTTP_BODY = 65536
MAX_PROFILE_BYTES = 16384
MAX_SUBSCRIBERS = 10000
MAX_DIAMETER_CONNECTIONS = 256
DIAMETER_IO_TIMEOUT = 5.0
CX_APPLICATION = 16777216
THREEGPP_VENDOR = 10415
RESULT_SUCCESS = 2001
RESULT_UNKNOWN_USER = 5001
RESULT_UNSUPPORTED = 3001


class DiameterError(ValueError):
    pass


def _u24(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFF:
        raise DiameterError("u24 out of range")
    return bytes(((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF))


def _read_u24(value: bytes) -> int:
    if len(value) != 3:
        raise DiameterError("invalid u24")
    return (value[0] << 16) | (value[1] << 8) | value[2]


def _u32(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise DiameterError("u32 out of range")
    return struct.pack("!I", value)


def _avp(code: int, value: bytes, *, flags: int = 0x40, vendor: int | None = None) -> bytes:
    if not 1 <= code <= 0xFFFFFF or len(value) > 65519:
        raise DiameterError("invalid AVP")
    if vendor is not None:
        if not 1 <= vendor <= 0xFFFFFFFF:
            raise DiameterError("invalid AVP vendor")
        flags |= 0x80
        body = _u32(vendor) + value
    else:
        body = value
    length = 8 + len(body)
    raw = struct.pack("!I", code) + bytes((flags,)) + _u24(length) + body
    return raw + b"\0" * ((4 - length % 4) % 4)


def _avp_text(code: int, value: str, *, vendor: int | None = None) -> bytes:
    return _avp(code, value.encode("ascii"), vendor=vendor)


def _avp_u32(code: int, value: int, *, vendor: int | None = None) -> bytes:
    return _avp(code, _u32(value), vendor=vendor)


@dataclass(frozen=True)
class Avp:
    code: int
    flags: int
    vendor: int | None
    value: bytes


@dataclass(frozen=True)
class DiameterMessage:
    flags: int
    command: int
    application: int
    hop_by_hop: int
    end_to_end: int
    avps: tuple[Avp, ...]

    def find(self, code: int, vendor: int | None = None) -> bytes | None:
        for avp in self.avps:
            if avp.code == code and avp.vendor == vendor:
                return avp.value
        return None


def _parse_avps(raw: bytes) -> tuple[Avp, ...]:
    values: list[Avp] = []
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < 8:
            raise DiameterError("truncated AVP")
        code = struct.unpack_from("!I", raw, offset)[0]
        flags = raw[offset + 4]
        length = _read_u24(raw[offset + 5:offset + 8])
        header_length = 12 if flags & 0x80 else 8
        if code == 0 or length < header_length or offset + length > len(raw):
            raise DiameterError("invalid AVP length")
        vendor = struct.unpack_from("!I", raw, offset + 8)[0] if flags & 0x80 else None
        value_start = offset + header_length
        padding = (4 - length % 4) % 4
        if offset + length + padding > len(raw) or raw[offset + length:offset + length + padding] != b"\0" * padding:
            raise DiameterError("invalid AVP padding")
        values.append(Avp(code, flags, vendor, raw[value_start:offset + length]))
        offset += length + padding
    return tuple(values)


def parse_message(raw: bytes) -> DiameterMessage:
    if len(raw) < 20 or raw[0] != 1:
        raise DiameterError("invalid Diameter header")
    length = _read_u24(raw[1:4])
    if length < 20 or length > MAX_DIAMETER or length != len(raw):
        raise DiameterError("invalid Diameter message length")
    flags = raw[4]
    command = _read_u24(raw[5:8])
    application = struct.unpack_from("!I", raw, 8)[0]
    hop_by_hop = struct.unpack_from("!I", raw, 12)[0]
    end_to_end = struct.unpack_from("!I", raw, 16)[0]
    return DiameterMessage(flags, command, application, hop_by_hop, end_to_end, _parse_avps(raw[20:]))


def build_message(
    *,
    flags: int,
    command: int,
    application: int,
    hop_by_hop: int,
    end_to_end: int,
    body: bytes,
) -> bytes:
    length = 20 + len(body)
    if length > MAX_DIAMETER:
        raise DiameterError("Diameter message too large")
    return bytes((1,)) + _u24(length) + bytes((flags,)) + _u24(command) + _u32(application) + _u32(hop_by_hop) + _u32(end_to_end) + body


def _vsa(application: int) -> bytes:
    return _avp(260, _avp_u32(266, THREEGPP_VENDOR) + _avp_u32(258, application))


def _vendor_text(code: int, value: str) -> bytes:
    return _avp_text(code, value, vendor=THREEGPP_VENDOR)


def _vendor_bytes(code: int, value: bytes) -> bytes:
    return _avp(code, value, vendor=THREEGPP_VENDOR)


def _vendor_grouped(code: int, children: bytes) -> bytes:
    return _avp(code, children, vendor=THREEGPP_VENDOR)


def _frame_read(sock: socket.socket) -> bytes:
    header = _read_exact(sock, 20)
    length = _read_u24(header[1:4])
    if length < 20 or length > MAX_DIAMETER:
        raise DiameterError("invalid Diameter frame length")
    return header + _read_exact(sock, length - 20)


def _read_exact(sock: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = sock.recv(length - len(result))
        if not chunk:
            raise ConnectionError("Diameter peer closed")
        result.extend(chunk)
    return bytes(result)


def _safe_ascii(value: bytes | None, limit: int) -> str:
    if value is None or not 1 <= len(value) <= limit:
        return ""
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError:
        return ""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        return ""
    return text


def _identity_field(item: dict[str, Any], name: str, limit: int) -> str:
    value = item.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{name} is required")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"invalid {name}") from exc
    result = _safe_ascii(raw, limit)
    if not result or any(char in result for char in ("|", '"', "\\")):
        raise ValueError(f"invalid {name}")
    return result


def _profile(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {"associated_uris": 8, "initial_filter_criteria": 4}
    if not isinstance(item, dict) or any(key not in allowed for key in item):
        raise ValueError("service_profile contains unsupported fields")
    result: dict[str, Any] = {}
    for key, limit in allowed.items():
        if key not in item:
            continue
        values = item[key]
        if not isinstance(values, list) or len(values) > limit:
            raise ValueError(f"{key} exceeds limit")
        validated: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError(f"invalid {key} value")
            try:
                raw = value.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(f"invalid {key} value") from exc
            parsed = _safe_ascii(raw, 2048)
            if not parsed.startswith(("sip:", "sips:")) or parsed in validated:
                raise ValueError(f"invalid {key} value")
            validated.append(parsed)
        result[key] = validated
    try:
        encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid service_profile") from exc
    if len(encoded) > MAX_PROFILE_BYTES:
        raise ValueError("service_profile exceeds limit")
    return result


@dataclass
class Subscriber:
    public_identity: str
    private_identity: str
    assigned_server_name: str
    xres: bytes
    service_profile: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


class HssStore:
    def __init__(self, max_subscribers: int = MAX_SUBSCRIBERS) -> None:
        if not 1 <= max_subscribers <= MAX_SUBSCRIBERS:
            raise ValueError("invalid subscriber limit")
        self.max_subscribers = max_subscribers
        self._items: dict[tuple[str, str], Subscriber] = {}
        self._lock = threading.RLock()

    def provision(self, item: dict[str, Any]) -> Subscriber:
        public = _identity_field(item, "public_identity", 2048)
        private = _identity_field(item, "private_identity", 1024)
        server = _identity_field(item, "assigned_server_name", 2048)
        if not public.startswith(("sip:", "sips:")) or not private or not server:
            raise ValueError("invalid subscriber identity or server")
        raw_xres = item.get("xres_base64")
        if not isinstance(raw_xres, str) or not 1 <= len(raw_xres) <= 1024:
            raise ValueError("xres_base64 is required")
        try:
            xres = base64.b64decode(raw_xres.encode("ascii"), validate=True)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid xres_base64") from exc
        if not 1 <= len(xres) <= 128:
            raise ValueError("xres exceeds limit")
        profile = _profile(item.get("service_profile", {}))
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        subscriber = Subscriber(public, private, server, xres, dict(profile), enabled)
        with self._lock:
            key = (public, private)
            if key not in self._items and len(self._items) >= self.max_subscribers:
                raise ValueError("subscriber capacity exhausted")
            self._items[key] = subscriber
        return subscriber

    def find(self, public: str, private: str | None = None) -> Subscriber | None:
        with self._lock:
            if private is not None:
                return self._items.get((public, private))
            for (candidate_public, _), item in self._items.items():
                if candidate_public == public:
                    return item
        return None

    def authorize(self, public: str, private: str) -> Subscriber | None:
        item = self.find(public, private)
        return item if item is not None and item.enabled else None


class HssApplication:
    def __init__(self, store: HssStore, *, origin_host: str, origin_realm: str) -> None:
        self.store = store
        self.origin_host = origin_host
        self.origin_realm = origin_realm
        self.debug = os.environ.get("IMS_HSS_DEBUG") == "1"

    def _common_body(self, request: DiameterMessage, result: int) -> bytes:
        session_id = request.find(263)
        body = b""
        if session_id is not None:
            body += _avp(263, session_id)
        body += _avp_text(264, self.origin_host)
        body += _avp_text(296, self.origin_realm)
        body += _avp_u32(268, result)
        body += _avp_u32(277, 1)
        if request.application == CX_APPLICATION:
            body += _vsa(CX_APPLICATION)
        return body

    def _answer(self, request: DiameterMessage, result: int, extra: bytes = b"") -> bytes:
        return build_message(
            flags=request.flags & 0x7F,
            command=request.command,
            application=request.application,
            hop_by_hop=request.hop_by_hop,
            end_to_end=request.end_to_end,
            body=self._common_body(request, result) + extra,
        )

    def _cea(self, request: DiameterMessage) -> bytes:
        body = _avp_text(264, self.origin_host) + _avp_text(296, self.origin_realm)
        body += _avp_u32(268, RESULT_SUCCESS)
        body += _avp(257, b"\0\1\x7f\0\0\1")
        body += _avp_u32(265, THREEGPP_VENDOR)
        body += _avp_u32(266, THREEGPP_VENDOR)
        body += _avp_text(269, "madis-lab-hss")
        body += _avp_u32(258, 4)
        body += _vsa(CX_APPLICATION)
        return build_message(flags=request.flags & 0x7F, command=257, application=0, hop_by_hop=request.hop_by_hop, end_to_end=request.end_to_end, body=body)

    @staticmethod
    def _identity(request: DiameterMessage) -> tuple[str, str, str]:
        public = _safe_ascii(request.find(601, THREEGPP_VENDOR), 2048)
        private = _safe_ascii(request.find(1), 1024)
        server = _safe_ascii(request.find(602, THREEGPP_VENDOR), 2048)
        return public, private, server

    @staticmethod
    def _mar_scheme(request: DiameterMessage) -> str:
        item = request.find(612, THREEGPP_VENDOR)
        if item is None:
            return ""
        try:
            nested = _parse_avps(item)
        except DiameterError:
            return ""
        for avp in nested:
            if avp.code == 608 and avp.vendor == THREEGPP_VENDOR:
                return _safe_ascii(avp.value, 128)
        return ""

    def handle(self, raw: bytes) -> bytes:
        try:
            request = parse_message(raw)
        except DiameterError as exc:
            if self.debug:
                print(f"diameter malformed request: {exc}", flush=True)
            return b""
        if self.debug:
            print(f"diameter request command={request.command} application={request.application} avps={len(request.avps)}", flush=True)
        if request.command == 257 and request.application == 0 and request.flags & 0x80:
            return self._cea(request)
        if request.command == 280 and request.application == 0 and request.flags & 0x80:
            return self._answer(request, RESULT_SUCCESS)
        if not request.flags & 0x80 or request.application != CX_APPLICATION:
            return self._answer(request, RESULT_UNSUPPORTED)
        public, private, requested_server = self._identity(request)
        item = self.store.authorize(public, private) if private else self.store.find(public)
        if item is None or not item.enabled:
            return self._answer(request, RESULT_UNKNOWN_USER)
        if request.command in (300, 301) and requested_server and requested_server != item.assigned_server_name:
            return self._answer(request, RESULT_UNKNOWN_USER)
        if request.command in (300, 301):
            return self._answer(request, RESULT_SUCCESS, _vendor_text(602, item.assigned_server_name))
        if request.command == 302:
            return self._answer(request, RESULT_SUCCESS, _vendor_text(602, item.assigned_server_name))
        if request.command == 303:
            if self._mar_scheme(request) != "Digest-AKAv1-MD5":
                return self._answer(request, RESULT_UNSUPPORTED)
            auth = secrets.token_bytes(16)
            children = _avp_u32(613, 0, vendor=THREEGPP_VENDOR)
            children += _vendor_text(608, "Digest-AKAv1-MD5")
            children += _vendor_bytes(609, auth)
            children += _vendor_bytes(610, item.xres)
            return self._answer(request, RESULT_SUCCESS, _vendor_grouped(612, children))
        return self._answer(request, RESULT_UNSUPPORTED)


class DiameterServer:
    def __init__(self, application: HssApplication, host: str, port: int, tls_context: ssl.SSLContext | None = None, max_connections: int = MAX_DIAMETER_CONNECTIONS) -> None:
        if not 1 <= max_connections <= MAX_DIAMETER_CONNECTIONS:
            raise ValueError("invalid Diameter connection limit")
        self.application = application
        self.host = host
        self.port = port
        self.tls_context = tls_context
        self._slots = threading.BoundedSemaphore(max_connections)
        self._listener: socket.socket | None = None
        self.bound_port = 0
        self._stop = threading.Event()

    def _client(self, conn: socket.socket) -> None:
        if not self._slots.acquire(blocking=False):
            conn.close()
            return
        try:
            conn.settimeout(DIAMETER_IO_TIMEOUT)
            if self.tls_context is not None:
                conn = self.tls_context.wrap_socket(conn, server_side=True)
                conn.settimeout(DIAMETER_IO_TIMEOUT)
            while not self._stop.is_set():
                try:
                    request = _frame_read(conn)
                except (ConnectionError, OSError, DiameterError):
                    return
                response = self.application.handle(request)
                if response:
                    try:
                        conn.sendall(response)
                    except OSError:
                        return
        finally:
            try:
                conn.close()
            finally:
                self._slots.release()

    def serve_forever(self) -> None:
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        listener = socket.socket(family, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(128)
        self._listener = listener
        self.bound_port = listener.getsockname()[1]
        while not self._stop.is_set():
            try:
                listener.settimeout(1.0)
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(target=self._client, args=(conn,), daemon=True)
            thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        self.bound_port = 0


def _request_id(public: str, private: str, visited: str, server: str) -> str:
    return hashlib.sha256(f"madis.ims.subscriber|register|{public}|{private}|{visited}|{server}".encode()).hexdigest()[:32]


def authorization_document(store: HssStore, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    schema = request.get("schema")
    operation = request.get("operation")
    public = request.get("public_identity")
    private = request.get("private_identity")
    visited = request.get("visited_network")
    server = request.get("server_name")
    if schema != "madis.ims.subscriber.authorization.v1" or operation != "authorize-register":
        return 400, {"ok": False, "error": "invalid authorization request"}
    if not all(isinstance(value, str) and 1 <= len(value) <= 2048 for value in (public, private, visited, server)):
        return 400, {"ok": False, "error": "invalid authorization fields"}
    request_id = _request_id(public, private, visited, server)
    item = store.authorize(public, private)
    response: dict[str, Any] = {
        "schema": "madis.ims.subscriber.authorization.v1",
        "operation": "authorize-register",
        "request_id": request_id,
        "public_identity": public,
        "private_identity": private,
    }
    if item is None:
        response.update({"decision": "deny", "reason": "subscriber-not-found"})
        return 200, response
    if item.assigned_server_name != server:
        response.update({"decision": "deny", "reason": "server-assignment-mismatch"})
        return 200, response
    response.update({"decision": "allow", "assigned_server_name": item.assigned_server_name, "service_profile": item.service_profile})
    return 200, response


class SubscriberHandler(http.server.BaseHTTPRequestHandler):
    server: "SubscriberHTTPServer"

    def log_message(self, *_args: Any) -> None:
        return

    def _authorized(self, provisioning: bool = False) -> bool:
        expected = self.server.provision_token if provisioning else self.server.http_token
        if not expected:
            return not provisioning
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {expected}")

    def _json_body(self) -> dict[str, Any] | None:
        if self.headers.get("Transfer-Encoding"):
            return None
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            return None
        if length < 1 or length > MAX_HTTP_BODY:
            return None
        body = self.rfile.read(length)
        if len(body) != length:
            return None
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _send_json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/healthz", "/readyz"):
            self._send_json(200, {"ready": True})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/ims/authorize":
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "authorization token required"})
                return
            request = self._json_body()
            if request is None:
                self._send_json(400, {"ok": False, "error": "bounded JSON body required"})
                return
            status, response = authorization_document(self.server.store, request)
            self._send_json(status, response)
            return
        if self.path == "/ims/provision":
            if not self._authorized(provisioning=True):
                self._send_json(401, {"ok": False, "error": "provisioning token required"})
                return
            request = self._json_body()
            if request is None or request.get("schema") != "madis.ims.subscriber.provision.v1" or request.get("operation") != "provision":
                self._send_json(400, {"ok": False, "error": "invalid provisioning request"})
                return
            try:
                self.server.store.provision(request)
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(201, {"ok": True, "provisioned": True})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


class SubscriberHTTPServer(http.server.ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], store: HssStore, http_token: str, provision_token: str) -> None:
        super().__init__(address, SubscriberHandler)
        self.store = store
        self.http_token = http_token
        self.provision_token = provision_token
        self.daemon_threads = True
        self.block_on_close = False


def _load_seed(store: HssStore, path: str | None) -> None:
    if not path:
        return
    with open(path, "rb") as handle:
        document = json.load(handle)
    if not isinstance(document, dict) or not isinstance(document.get("subscribers"), list):
        raise ValueError("seed file must contain a subscribers array")
    for item in document["subscribers"]:
        if not isinstance(item, dict):
            raise ValueError("seed subscriber must be an object")
        store.provision(item)


def _token(value: str, name: str) -> str:
    if value and len(value) < 16:
        raise ValueError(f"{name} must be at least 16 characters")
    return value


def _tls_context(cert: str | None, key: str | None) -> ssl.SSLContext | None:
    if not cert and not key:
        return None
    if not cert or not key:
        raise ValueError("TLS certificate and key must be supplied together")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diameter-host", default="127.0.0.1")
    parser.add_argument("--diameter-port", type=int, default=3868)
    parser.add_argument("--diameter-cert")
    parser.add_argument("--diameter-key")
    parser.add_argument("--diameter-max-connections", type=int, default=MAX_DIAMETER_CONNECTIONS)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8444)
    parser.add_argument("--http-cert")
    parser.add_argument("--http-key")
    parser.add_argument("--http-token", default="")
    parser.add_argument("--provision-token", default="")
    parser.add_argument("--origin-host", default="hss.lab.local")
    parser.add_argument("--origin-realm", default="example.com")
    parser.add_argument("--seed-json")
    args = parser.parse_args(argv)
    try:
        http_token = _token(args.http_token, "http-token")
        provision_token = _token(args.provision_token, "provision-token")
        if not _is_loopback(args.http_host) and not http_token:
            raise ValueError("non-loopback HTTP requires --http-token")
        store = HssStore()
        _load_seed(store, args.seed_json)
        application = HssApplication(store, origin_host=args.origin_host, origin_realm=args.origin_realm)
        diameter = DiameterServer(application, args.diameter_host, args.diameter_port, _tls_context(args.diameter_cert, args.diameter_key), args.diameter_max_connections)
        diameter_thread = threading.Thread(target=diameter.serve_forever, daemon=True)
        diameter_thread.start()
        http_server = SubscriberHTTPServer((args.http_host, args.http_port), store, http_token, provision_token)
        http_tls = _tls_context(args.http_cert, args.http_key)
        if http_tls is not None:
            http_server.socket = http_tls.wrap_socket(http_server.socket, server_side=True)
        try:
            http_server.serve_forever()
        finally:
            http_server.shutdown()
            http_server.server_close()
            diameter.close()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"IMS HSS lab adapter failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
