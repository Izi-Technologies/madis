#!/usr/bin/env python3
"""Small, external RTPEngine-ng compatible media module for the IMS lab.

This process deliberately owns the media plane outside Madis.  It accepts the
bounded offer/answer/delete control messages already emitted by ``rtpengine.mko``
and relays one RTP/RTCP audio stream per call.  It is a lab module, not a
production media server: ICE, DTLS-SRTP termination, codec transcoding,
recording, and multi-stream policy are intentionally out of scope.

The control socket is loopback-only by default.  Put it on a private network
and add an explicit source allow-list before using it in a multi-host lab.
"""

from __future__ import annotations

import argparse
import ipaddress
import selectors
import socket
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any


MAX_CONTROL_PACKET = 65535
MAX_SDP = 65535
MAX_MEDIA_PACKET = 8192
MAX_CALL_ID = 512
MAX_TAG = 256
MAX_BENCODE_DEPTH = 32


class BencodeError(ValueError):
    """Raised for malformed or oversized RTPEngine control payloads."""


def _bencode(value: Any) -> bytes:
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        return _bencode(value.encode("utf-8"))
    if isinstance(value, int) and not isinstance(value, bool):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items: list[tuple[bytes, Any]] = []
        for key, item in value.items():
            if not isinstance(key, (str, bytes)):
                raise BencodeError("dictionary key must be text")
            raw_key = key if isinstance(key, bytes) else key.encode("utf-8")
            items.append((raw_key, item))
        items.sort(key=lambda item: item[0])
        return b"d" + b"".join(_bencode(key) + _bencode(item) for key, item in items) + b"e"
    raise BencodeError("unsupported bencode type")


def bencode_dict(value: dict[str, Any]) -> bytes:
    encoded = _bencode(value)
    if len(encoded) > MAX_CONTROL_PACKET:
        raise BencodeError("control response too large")
    return encoded


def _bdecode(data: bytes, offset: int = 0, depth: int = 0) -> tuple[Any, int]:
    if offset >= len(data):
        raise BencodeError("truncated bencode")
    if depth > MAX_BENCODE_DEPTH:
        raise BencodeError("bencode nesting exceeds limit")
    marker = data[offset:offset + 1]
    if marker == b"i":
        end = data.find(b"e", offset + 1)
        if end < 0:
            raise BencodeError("unterminated integer")
        raw = data[offset + 1:end]
        if not raw or (raw.startswith(b"0") and raw != b"0") or raw == b"-0":
            raise BencodeError("invalid integer")
        try:
            return int(raw), end + 1
        except ValueError as exc:
            raise BencodeError("invalid integer") from exc
    if marker == b"l":
        values: list[Any] = []
        cursor = offset + 1
        while True:
            if cursor >= len(data):
                raise BencodeError("unterminated list")
            if data[cursor:cursor + 1] == b"e":
                return values, cursor + 1
            value, cursor = _bdecode(data, cursor, depth + 1)
            values.append(value)
            if len(values) > 32:
                raise BencodeError("list too large")
    if marker == b"d":
        values: dict[bytes, Any] = {}
        cursor = offset + 1
        while True:
            if cursor >= len(data):
                raise BencodeError("unterminated dictionary")
            if data[cursor:cursor + 1] == b"e":
                return values, cursor + 1
            key, cursor = _bdecode(data, cursor, depth + 1)
            if not isinstance(key, bytes):
                raise BencodeError("dictionary key must be a byte string")
            if key in values:
                raise BencodeError("duplicate dictionary key")
            value, cursor = _bdecode(data, cursor, depth + 1)
            values[key] = value
            if len(values) > 64:
                raise BencodeError("dictionary too large")
    if marker[:1].isdigit():
        colon = data.find(b":", offset)
        if colon < 0 or colon - offset > 6:
            raise BencodeError("invalid byte-string length")
        raw_length = data[offset:colon]
        if not raw_length or (raw_length.startswith(b"0") and raw_length != b"0"):
            raise BencodeError("invalid byte-string length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BencodeError("invalid byte-string length") from exc
        if length < 0 or length > MAX_CONTROL_PACKET or colon + 1 + length > len(data):
            raise BencodeError("byte-string exceeds limit")
        end = colon + 1 + length
        return data[colon + 1:end], end
    raise BencodeError("unknown bencode marker")


def bdecode_dict(data: bytes) -> dict[bytes, Any]:
    if not data or len(data) > MAX_CONTROL_PACKET:
        raise BencodeError("invalid control payload size")
    value, offset = _bdecode(data)
    if offset != len(data) or not isinstance(value, dict):
        raise BencodeError("control payload must be one dictionary")
    return value


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, bytes) or not 1 <= len(value) <= limit:
        raise ValueError(f"invalid {field}")
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid {field}") from exc
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise ValueError(f"invalid {field}")
    return text


def _sdp_text(value: Any) -> str:
    if not isinstance(value, bytes) or not 1 <= len(value) <= MAX_SDP:
        raise ValueError("invalid sdp")
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid sdp") from exc
    for char in text:
        code = ord(char)
        if code == 0 or (code < 0x20 and char not in ("\r", "\n", "\t")) or code == 0x7F:
            raise ValueError("invalid sdp")
    return text


def _ip_address(value: str) -> ipaddress._BaseAddress | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if address.is_unspecified:
        return None
    return address


@dataclass
class SdpDescription:
    address: tuple[str, int] | None
    media_line_index: int


def parse_sdp(sdp: str) -> SdpDescription:
    if not 1 <= len(sdp.encode("utf-8")) <= MAX_SDP:
        raise ValueError("SDP exceeds limit")
    if "\x00" in sdp or not sdp.startswith("v=0\r\n"):
        raise ValueError("SDP must start with v=0")
    lines = sdp.split("\r\n")
    connection: ipaddress._BaseAddress | None = None
    media_line_index = -1
    media_port = 0
    for index, line in enumerate(lines):
        if line.startswith("c=IN IP4 ") or line.startswith("c=IN IP6 "):
            address = _ip_address(line.split(" ", 2)[-1])
            if address is None:
                # 0.0.0.0 is a valid hold address but is not a relay target.
                continue
            if connection is not None:
                raise ValueError("multiple connection addresses are unsupported")
            connection = address
        if line.startswith("m=audio "):
            if media_line_index >= 0:
                raise ValueError("multiple audio streams are unsupported")
            fields = line.split()
            if len(fields) < 4:
                raise ValueError("malformed audio media line")
            try:
                media_port = int(fields[1])
            except ValueError as exc:
                raise ValueError("invalid audio media port") from exc
            if not 1 <= media_port <= 65535:
                raise ValueError("invalid audio media port")
            media_line_index = index
    if media_line_index < 0 or connection is None:
        raise ValueError("SDP needs one routable audio stream")
    return SdpDescription((str(connection), media_port), media_line_index)


def rewrite_sdp(sdp: str, advertised_ip: str, media_port: int) -> str:
    if not 1 <= media_port <= 65535:
        raise ValueError("invalid relay port")
    address = _ip_address(advertised_ip)
    if address is None:
        raise ValueError("invalid advertised media address")
    family = "IP6" if address.version == 6 else "IP4"
    lines = sdp.split("\r\n")
    connection_index = next(
        (index for index, line in enumerate(lines) if line.startswith("c=IN IP4 ") or line.startswith("c=IN IP6 ")),
        -1,
    )
    media_index = next((index for index, line in enumerate(lines) if line.startswith("m=audio ")), -1)
    if connection_index < 0 or media_index < 0:
        raise ValueError("SDP needs one connection and audio line")
    fields = lines[media_index].split()
    if len(fields) < 4:
        raise ValueError("malformed audio media line")
    fields[1] = str(media_port)
    lines[connection_index] = f"c=IN {family} {address}"
    lines[media_index] = " ".join(fields)
    return "\r\n".join(lines)


def _valid_rtp_packet(packet: bytes) -> bool:
    if not 12 <= len(packet) <= MAX_MEDIA_PACKET:
        return False
    # RTP and RTCP both carry version 2.  We do not inspect payload types here.
    return (packet[0] >> 6) == 2


@dataclass
class Leg:
    socket: socket.socket
    advertised: tuple[str, int]
    observed: tuple[str, int] | None = None


@dataclass
class Session:
    call_id: str
    from_tag: str
    offer: Leg
    to_tag: str = ""
    answer: Leg | None = None
    last_activity: float = 0.0


class MediaRelay:
    """RTPEngine-ng control adapter and bounded one-stream relay."""

    def __init__(
        self,
        *,
        media_bind: str = "127.0.0.1",
        media_ip: str = "127.0.0.1",
        media_min: int = 30000,
        media_max: int = 39999,
        max_sessions: int = 4096,
        session_timeout: float = 3600.0,
        control_allow: set[str] | None = None,
    ) -> None:
        if not 1 <= media_min <= media_max <= 65535:
            raise ValueError("invalid media port range")
        if not 1 <= max_sessions <= 1_000_000:
            raise ValueError("invalid session limit")
        if not 1.0 <= session_timeout <= 86400.0:
            raise ValueError("invalid session timeout")
        advertised = _ip_address(media_ip)
        if advertised is None:
            raise ValueError("media_ip must be a routable address")
        self.media_bind = media_bind
        self.media_ip = str(advertised)
        self.media_family = socket.AF_INET6 if advertised.version == 6 else socket.AF_INET
        self.media_min = media_min
        self.media_max = media_max
        self.max_sessions = max_sessions
        self.session_timeout = session_timeout
        self.control_allow = control_allow or {"127.0.0.1", "::1"}
        self.sessions: dict[str, Session] = {}
        self._selector = selectors.DefaultSelector()
        self._control: socket.socket | None = None
        self.control_address: tuple[str, int] | None = None
        self._stop = False

    def _allocate_socket(self) -> socket.socket:
        sock = socket.socket(self.media_family, socket.SOCK_DGRAM)
        sock.setblocking(False)
        for port in range(self.media_min, self.media_max + 1):
            try:
                sock.bind((self.media_bind, port))
                self._selector.register(sock, selectors.EVENT_READ, self._handle_media_socket)
                return sock
            except OSError:
                continue
        sock.close()
        raise RuntimeError("media port range exhausted")

    def _close_leg(self, leg: Leg | None) -> None:
        if leg is None:
            return
        try:
            self._selector.unregister(leg.socket)
        except (KeyError, ValueError):
            pass
        leg.socket.close()

    def _delete_session(self, call_id: str) -> bool:
        session = self.sessions.pop(call_id, None)
        if session is None:
            return False
        self._close_leg(session.offer)
        self._close_leg(session.answer)
        return True

    def _error(self, reason: str) -> bytes:
        return bencode_dict({"result": "error", "error-reason": reason[:128]})

    def _offer(self, call_id: str, from_tag: str, sdp: str) -> bytes:
        if call_id in self.sessions:
            self._delete_session(call_id)
        if len(self.sessions) >= self.max_sessions:
            return self._error("capacity-exhausted")
        try:
            description = parse_sdp(sdp)
            sock = self._allocate_socket()
            port = sock.getsockname()[1]
            rewritten = rewrite_sdp(sdp, self.media_ip, port)
        except (ValueError, RuntimeError, OSError) as exc:
            if "sock" in locals():
                self._close_leg(Leg(sock, ("0.0.0.0", 1)))
            return self._error(str(exc))
        self.sessions[call_id] = Session(call_id, from_tag, Leg(sock, description.address), last_activity=time.monotonic())
        return bencode_dict({"result": "ok", "sdp": rewritten})

    def _answer(self, call_id: str, from_tag: str, to_tag: str, sdp: str) -> bytes:
        session = self.sessions.get(call_id)
        if session is None or session.from_tag != from_tag or session.answer is not None:
            return self._error("unknown-or-reused-dialog")
        try:
            description = parse_sdp(sdp)
            sock = self._allocate_socket()
            port = sock.getsockname()[1]
            rewritten = rewrite_sdp(sdp, self.media_ip, port)
        except (ValueError, RuntimeError, OSError) as exc:
            if "sock" in locals():
                self._close_leg(Leg(sock, ("0.0.0.0", 1)))
            return self._error(str(exc))
        session.to_tag = to_tag
        session.answer = Leg(sock, description.address)
        session.last_activity = time.monotonic()
        return bencode_dict({"result": "ok", "sdp": rewritten})

    def handle_payload(self, payload: bytes) -> bytes:
        """Handle one bencoded command without the ng cookie prefix."""
        try:
            command = bdecode_dict(payload)
            operation = _text(command.get(b"command"), "command", 32).lower()
            if operation == "ping":
                return bencode_dict({"result": "ok"})
            call_id = _text(command.get(b"call-id"), "call-id", MAX_CALL_ID)
            if operation == "delete":
                self._delete_session(call_id)
                return bencode_dict({"result": "ok"})
            from_tag = _text(command.get(b"from-tag"), "from-tag", MAX_TAG)
            sdp = _sdp_text(command.get(b"sdp"))
            if operation == "offer":
                return self._offer(call_id, from_tag, sdp)
            if operation == "answer":
                to_tag = _text(command.get(b"to-tag"), "to-tag", MAX_TAG)
                return self._answer(call_id, from_tag, to_tag, sdp)
            return self._error("unsupported-command")
        except (BencodeError, RecursionError, ValueError) as exc:
            return self._error(str(exc))

    def _relay_packet(self, session: Session, leg: Leg, packet: bytes, source: tuple[str, int]) -> None:
        if not _valid_rtp_packet(packet):
            return
        if leg.observed is not None and leg.observed != source:
            return
        leg.observed = source
        session.last_activity = time.monotonic()
        target: Leg | None = None
        for session in self.sessions.values():
            if session.offer is leg:
                target = session.answer
                break
            if session.answer is leg:
                target = session.offer
                break
        if target is None:
            return
        destination = target.observed or target.advertised
        try:
            target.socket.sendto(packet, destination)
        except OSError:
            # The signaling path owns failure reporting. Media packets are
            # best-effort and must not take down the sidecar process.
            return

    def _handle_media_socket(self, sock: socket.socket) -> None:
        try:
            packet, source = sock.recvfrom(MAX_MEDIA_PACKET)
        except OSError:
            return
        for session in tuple(self.sessions.values()):
            if session.offer.socket is sock:
                self._relay_packet(session, session.offer, packet, source)
                return
            if session.answer is not None and session.answer.socket is sock:
                self._relay_packet(session, session.answer, packet, source)
                return

    def _expire_sessions(self) -> None:
        deadline = time.monotonic() - self.session_timeout
        for call_id, session in tuple(self.sessions.items()):
            if session.last_activity <= deadline:
                self._delete_session(call_id)

    def serve(self, control_host: str = "127.0.0.1", control_port: int = 2223) -> None:
        family = socket.AF_INET6 if ":" in control_host else socket.AF_INET
        control = socket.socket(family, socket.SOCK_DGRAM)
        control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        control.bind((control_host, control_port))
        control.setblocking(False)
        self._control = control
        self.control_address = (control_host, control.getsockname()[1])
        self._stop = False
        self._selector.register(control, selectors.EVENT_READ, self._handle_control_socket)
        try:
            while not self._stop:
                try:
                    events = self._selector.select(timeout=1.0)
                except (OSError, ValueError):
                    break
                for key, _ in events:
                    key.data(key.fileobj)
                self._expire_sessions()
        finally:
            self.close()

    def _handle_control_socket(self, control: socket.socket) -> None:
        try:
            packet, source = control.recvfrom(MAX_CONTROL_PACKET)
        except OSError:
            return
        if source[0] not in self.control_allow:
            return
        separator = packet.find(b" ")
        if separator <= 0 or separator + 1 >= len(packet):
            return
        cookie = packet[:separator]
        payload = packet[separator + 1:]
        if len(cookie) > 64:
            return
        response = self.handle_payload(payload)
        try:
            control.sendto(cookie + b" " + response, source)
        except OSError:
            return

    def close(self) -> None:
        self._stop = True
        for call_id in tuple(self.sessions):
            self._delete_session(call_id)
        if self._control is not None:
            try:
                self._selector.unregister(self._control)
            except (KeyError, ValueError):
                pass
            self._control.close()
            self._control = None
            self.control_address = None
        self._selector.close()


def _parse_allowlist(raw: str) -> set[str]:
    values = {item.strip() for item in raw.split(",") if item.strip()}
    if not values:
        raise ValueError("control allow-list cannot be empty")
    for item in values:
        ipaddress.ip_address(item)
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=2223)
    parser.add_argument("--control-allow", default="127.0.0.1,::1")
    parser.add_argument("--media-bind", default="127.0.0.1")
    parser.add_argument("--media-ip", default="127.0.0.1")
    parser.add_argument("--media-min", type=int, default=30000)
    parser.add_argument("--media-max", type=int, default=39999)
    parser.add_argument("--max-sessions", type=int, default=4096)
    parser.add_argument("--session-timeout", type=float, default=3600.0)
    args = parser.parse_args(argv)
    try:
        relay = MediaRelay(
            media_bind=args.media_bind,
            media_ip=args.media_ip,
            media_min=args.media_min,
            media_max=args.media_max,
            max_sessions=args.max_sessions,
            session_timeout=args.session_timeout,
            control_allow=_parse_allowlist(args.control_allow),
        )
        relay.serve(args.control_host, args.control_port)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"media module failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
