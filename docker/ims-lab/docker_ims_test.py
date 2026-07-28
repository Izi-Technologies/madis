"""Two-party IMS/Cx/AKA and RTP smoke test for the Docker lab."""

from __future__ import annotations

import hashlib
import os
import re
import socket
import time
import uuid


MADIS_HOST = os.environ.get("MADIS_HOST", "madis")
MADIS_SIP_PORT = int(os.environ.get("MADIS_SIP_PORT", "5060"))
CLIENT_MEDIA_IP = os.environ.get("CLIENT_MEDIA_IP", "172.30.0.5")
MEDIA_HOST = os.environ.get("MEDIA_HOST", "172.30.0.3")


def status(message: str) -> int:
    return int(message.split("\r\n", 1)[0].split()[1])


def headers(message: str) -> dict[str, str]:
    head = message.split("\r\n\r\n", 1)[0]
    values: dict[str, str] = {}
    for line in head.split("\r\n")[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            values[name.lower()] = value.strip()
    return values


def header_line(values: dict[str, str], name: str) -> str:
    return f"{name}: {values[name.lower()]}\r\n"


def header_lines(message: str, name: str) -> str:
    result: list[str] = []
    for line in message.split("\r\n")[1:]:
        if ":" not in line:
            continue
        header_name, value = line.split(":", 1)
        if header_name.lower() == name.lower():
            result.append(f"{name}: {value.strip()}\r\n")
    return "".join(result)


def digest_params(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(
        r"([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(?:\"([^\"]*)\"|([^,\s]+))",
        value,
    ):
        result[match.group(1).lower()] = (
            match.group(2) if match.group(2) is not None else match.group(3)
        )
    return result


def sdp_media_port(message: str) -> int:
    body = message.split("\r\n\r\n", 1)[1]
    for line in body.split("\r\n"):
        if line.startswith("m=audio "):
            return int(line.split()[1])
    raise AssertionError("missing audio SDP media line")


class SipClient:
    def __init__(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("0.0.0.0", 0))
        self.socket.settimeout(5.0)
        self.address = self.socket.getsockname()

    def send(self, message: str) -> None:
        self.socket.sendto(message.encode("ascii"), (MADIS_HOST, MADIS_SIP_PORT))

    def receive(self, predicate) -> str:
        deadline = time.monotonic() + 8.0
        seen: list[str] = []
        while time.monotonic() < deadline:
            self.socket.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                raw, _ = self.socket.recvfrom(65535)
            except socket.timeout:
                break
            message = raw.decode("ascii", "replace")
            if predicate(message):
                return message
            seen.append(" | ".join(message.split("\r\n")[:5]))
        raise AssertionError(f"SIP response did not arrive; saw {seen}")

    def close(self) -> None:
        self.socket.close()


def register(client: SipClient, user: str, xres: str) -> None:
    call_id = f"register-{user}-{uuid.uuid4().hex[:12]}"
    from_header = f"<sip:{user}@example.com>;tag={user}-register"
    contact = f"<sip:{user}@{CLIENT_MEDIA_IP}:{client.address[1]}>"

    def make_register(cseq: int, branch: str, authorization: str = "") -> str:
        extra = f"Authorization: {authorization}\r\n" if authorization else ""
        return (
            "REGISTER sip:example.com SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {CLIENT_MEDIA_IP}:{client.address[1]};branch={branch}\r\n"
            "Max-Forwards: 70\r\n"
            f"From: {from_header}\r\n"
            f"To: <sip:{user}@example.com>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq} REGISTER\r\n"
            f"Contact: {contact}\r\n"
            "Expires: 300\r\n"
            f"{extra}Content-Length: 0\r\n\r\n"
        )

    client.send(make_register(1, "z9hG4bK-" + uuid.uuid4().hex))
    challenge = client.receive(lambda message: status(message) in (401, 407))
    if status(challenge) != 401:
        raise AssertionError(f"expected 401 REGISTER challenge, got {status(challenge)}")
    params = digest_params(headers(challenge)["www-authenticate"])
    if params.get("algorithm", "").lower() != "akav1-md5" or params.get("qop") != "auth":
        raise AssertionError(f"unexpected AKA challenge: {params}")
    uri = "sip:example.com"
    cnonce = "docker-ims-cnonce"
    nc = "00000001"
    ha1 = hashlib.md5(f"{user}@example.com:example.com:{xres}".encode("ascii")).hexdigest()
    ha2 = hashlib.md5(f"REGISTER:{uri}".encode("ascii")).hexdigest()
    response = hashlib.md5(
        f"{ha1}:{params['nonce']}:{nc}:{cnonce}:auth:{ha2}".encode("ascii")
    ).hexdigest()
    authorization = (
        f'Digest username="{user}@example.com", realm="example.com", '
        f'nonce="{params["nonce"]}", uri="{uri}", response="{response}", '
        f"algorithm=AKAv1-MD5, qop=auth, nc={nc}, cnonce=\"{cnonce}\""
    )
    client.send(make_register(2, "z9hG4bK-" + uuid.uuid4().hex, authorization))
    accepted = client.receive(lambda message: status(message) == 200)
    if status(accepted) != 200:
        raise AssertionError("REGISTER was not accepted")


def expect_register_rejected(client: SipClient, user: str) -> None:
    call_id = f"reject-{user}-{uuid.uuid4().hex[:12]}"
    message = (
        "REGISTER sip:example.com SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {CLIENT_MEDIA_IP}:{client.address[1]};branch=z9hG4bK-{uuid.uuid4().hex}\r\n"
        "Max-Forwards: 70\r\n"
        f"From: <sip:{user}@example.com>;tag={user}-rejected\r\n"
        f"To: <sip:{user}@example.com>\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{user}@{CLIENT_MEDIA_IP}:{client.address[1]}>\r\n"
        "Expires: 300\r\n"
        "Content-Length: 0\r\n\r\n"
    )
    client.send(message)
    rejected = client.receive(lambda item: status(item) in (403, 503))
    if status(rejected) != 503:
        raise AssertionError(f"expected 503 for rejected IMS vector, got {status(rejected)}")


def run_call(alice: SipClient, bob: SipClient) -> None:
    call_id = "call-" + uuid.uuid4().hex[:12]
    alice_tag = "alice-call"
    branch = "z9hG4bK-" + uuid.uuid4().hex
    alice_media_port = alice.media.getsockname()[1]
    bob_media_port = bob.media.getsockname()[1]
    offer_sdp = (
        "v=0\r\n"
        "o=- 1 1 IN IP4 " + CLIENT_MEDIA_IP + "\r\n"
        "s=-\r\n"
        "c=IN IP4 " + CLIENT_MEDIA_IP + "\r\n"
        "t=0 0\r\n"
        f"m=audio {alice_media_port} RTP/AVP 0\r\n"
    )
    invite = (
        "INVITE sip:bob@example.com SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {CLIENT_MEDIA_IP}:{alice.address[1]};branch={branch}\r\n"
        "Max-Forwards: 70\r\n"
        f"From: <sip:alice@example.com>;tag={alice_tag}\r\n"
        "To: <sip:bob@example.com>\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 1 INVITE\r\n"
        f"Contact: <sip:alice@{CLIENT_MEDIA_IP}:{alice.address[1]}>\r\n"
        "Content-Type: application/sdp\r\n"
        f"Content-Length: {len(offer_sdp)}\r\n\r\n{offer_sdp}"
    )
    alice.send(invite)
    challenge = alice.receive(lambda message: status(message) == 401)
    params = digest_params(headers(challenge)["www-authenticate"])
    cnonce = "docker-ims-invite-cnonce"
    nc = "00000001"
    ha1 = hashlib.md5(b"alice@example.com:example.com:xres-alice").hexdigest()
    ha2 = hashlib.md5(b"INVITE:sip:bob@example.com").hexdigest()
    response = hashlib.md5(
        f"{ha1}:{params['nonce']}:{nc}:{cnonce}:auth:{ha2}".encode("ascii")
    ).hexdigest()
    authorization = (
        'Digest username="alice@example.com", realm="example.com", '
        f'nonce="{params["nonce"]}", uri="sip:bob@example.com", '
        f'response="{response}", algorithm=AKAv1-MD5, qop=auth, nc={nc}, '
        f'cnonce="{cnonce}"'
    )
    authenticated = invite.replace(
        f"branch={branch}", f"branch={branch}-authenticated"
    ).replace(
        "CSeq: 1 INVITE\r\n", "CSeq: 2 INVITE\r\n"
    ).replace(
        "Content-Type: application/sdp\r\n",
        f"Authorization: {authorization}\r\nContent-Type: application/sdp\r\n",
    )
    alice.send(authenticated)

    forwarded_invite = bob.receive(lambda message: message.startswith("INVITE "))
    forwarded_offer_port = sdp_media_port(forwarded_invite)
    if forwarded_offer_port == alice_media_port or "c=IN IP4 172.30.0.3" not in forwarded_invite:
        raise AssertionError("Madis did not rewrite the forwarded offer for media")
    invite_headers = headers(forwarded_invite)
    bob_tag = "bob-call"
    ringing = (
        "SIP/2.0 180 Ringing\r\n"
        + header_lines(forwarded_invite, "Via")
        + header_line(invite_headers, "from")
        + f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
        + header_line(invite_headers, "call-id")
        + header_line(invite_headers, "cseq")
        + "Content-Length: 0\r\n\r\n"
    )
    bob.send(ringing)
    alice.receive(lambda message: status(message) == 180)

    answer_sdp = (
        "v=0\r\n"
        "o=- 2 2 IN IP4 " + CLIENT_MEDIA_IP + "\r\n"
        "s=-\r\n"
        "c=IN IP4 " + CLIENT_MEDIA_IP + "\r\n"
        "t=0 0\r\n"
        f"m=audio {bob_media_port} RTP/AVP 0\r\n"
    )
    ok = (
        "SIP/2.0 200 OK\r\n"
        + header_lines(forwarded_invite, "Via")
        + header_line(invite_headers, "from")
        + f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
        + header_line(invite_headers, "call-id")
        + header_line(invite_headers, "cseq")
        + f"Contact: <sip:bob@{CLIENT_MEDIA_IP}:{bob.address[1]}>\r\n"
        + "Content-Type: application/sdp\r\n"
        + f"Content-Length: {len(answer_sdp)}\r\n\r\n{answer_sdp}"
    )
    bob.send(ok)
    accepted = alice.receive(lambda message: status(message) == 200)
    forwarded_answer_port = sdp_media_port(accepted)
    if forwarded_answer_port == bob_media_port or "c=IN IP4 172.30.0.3" not in accepted:
        raise AssertionError("Madis did not rewrite the answer for media")

    alice_packet = b"\x80\x00\x00\x01\x00\x00\x00\x01\x12\x34\x56\x78docker-alice"
    alice.media.sendto(alice_packet, (MEDIA_HOST, forwarded_offer_port))
    received_by_bob, _ = bob.media.recvfrom(4096)
    if received_by_bob != alice_packet:
        raise AssertionError("Alice RTP did not reach Bob")
    bob_packet = b"\x80\x00\x00\x02\x00\x00\x00\x02\x87\x65\x43\x21docker-bob"
    bob.media.sendto(bob_packet, (MEDIA_HOST, forwarded_answer_port))
    received_by_alice, _ = alice.media.recvfrom(4096)
    if received_by_alice != bob_packet:
        raise AssertionError("Bob RTP did not reach Alice")

    ack = (
        "ACK sip:bob@example.com SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {CLIENT_MEDIA_IP}:{alice.address[1]};branch=z9hG4bK-{uuid.uuid4().hex}\r\n"
        "Max-Forwards: 70\r\n"
        f"From: <sip:alice@example.com>;tag={alice_tag}\r\n"
        f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 1 ACK\r\n"
        "Content-Length: 0\r\n\r\n"
    )
    alice.send(ack)
    bob.receive(lambda message: message.startswith("ACK "))
    bye = (
        "BYE sip:bob@example.com SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {CLIENT_MEDIA_IP}:{alice.address[1]};branch=z9hG4bK-{uuid.uuid4().hex}\r\n"
        "Max-Forwards: 70\r\n"
        f"From: <sip:alice@example.com>;tag={alice_tag}\r\n"
        f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 2 BYE\r\n"
        "Content-Length: 0\r\n\r\n"
    )
    alice.send(bye)
    bye_request = bob.receive(lambda message: message.startswith("BYE "))
    bye_headers = headers(bye_request)
    bye_ok = (
        "SIP/2.0 200 OK\r\n"
        + header_lines(bye_request, "Via")
        + header_line(bye_headers, "from")
        + header_line(bye_headers, "to")
        + header_line(bye_headers, "call-id")
        + header_line(bye_headers, "cseq")
        + "Content-Length: 0\r\n\r\n"
    )
    bob.send(bye_ok)
    alice.receive(lambda message: status(message) == 200 and headers(message).get("cseq", "").startswith("2 BYE"))


def main() -> int:
    alice = SipClient()
    bob = SipClient()
    alice.media = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bob.media = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    alice.media.bind(("0.0.0.0", 0))
    bob.media.bind(("0.0.0.0", 0))
    alice.media.settimeout(5.0)
    bob.media.settimeout(5.0)
    try:
        expect_register_rejected(alice, "missing")
        expect_register_rejected(alice, "barred")
        register(alice, "alice", "xres-alice")
        register(bob, "bob", "xres-bob")
        run_call(alice, bob)
        print("Docker IMS lab passed: P-/I-/S-CSCF Cx/AKA REGISTER, authenticated INVITE, SDP relay, bidirectional RTP, ACK, BYE")
        return 0
    finally:
        alice.close()
        bob.close()
        alice.media.close()
        bob.media.close()


if __name__ == "__main__":
    raise SystemExit(main())
