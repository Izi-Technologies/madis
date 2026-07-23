#!/usr/bin/env python3
"""Independent hashlib reference vectors for SIP Digest authentication."""

from __future__ import annotations

import hashlib


def digest(name: str, value: str) -> str:
    return hashlib.new(name, value.encode()).hexdigest()


def qop_response(name: str, ha1: str, method: str, uri: str, nonce: str, nc: str, cnonce: str, qop: str) -> str:
    ha2 = digest(name, f"{method}:{uri}")
    return digest(name, f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")


def sess_response(name: str, ha1: str, method: str, uri: str, nonce: str, cnonce: str) -> str:
    sess_ha1 = digest(name, f"{ha1}:{nonce}:{cnonce}")
    ha2 = digest(name, f"{method}:{uri}")
    return digest(name, f"{sess_ha1}:{nonce}:{ha2}")


def main() -> int:
    nonce = "dcd98b7102dd2f0e8b11d0f600bfb0c093"
    nc = "00000001"
    cnonce = "0a4f113b"
    method = "GET"
    uri = "/dir/index.html"

    md5_ha1 = "939e7578ed9e3c518a452acee763bce9"
    sha_ha1 = "3ba6cd94661c5ef34598040c868f13b8775df29109986be50ad35ae537dd3aa4"
    vectors = {
        "md5-auth": qop_response("md5", md5_ha1, method, uri, nonce, nc, cnonce, "auth"),
        "sha256-auth": qop_response("sha256", sha_ha1, method, uri, nonce, nc, cnonce, "auth"),
        "md5-sess": sess_response("md5", md5_ha1, method, uri, nonce, cnonce),
        "sha256-sess": sess_response("sha256", sha_ha1, method, uri, nonce, cnonce),
    }
    expected = {
        "md5-auth": "6629fae49393a05397450978507c4ef1",
        "sha256-auth": "5abdd07184ba512a22c53f41470e5eea7dcaa3a93a59b630c13dfe0a5dc6e38b",
        "md5-sess": "4726bc10c33fa6cb357eb27807b1cce8",
        "sha256-sess": "6f421709505a71923c950606510a113314a303e5224f5d6390e4ad42cb718479",
    }
    for name, value in vectors.items():
        if value != expected[name]:
            raise SystemExit(f"{name}: got {value}, want {expected[name]}")
    print("auth reference matrix: MD5/SHA-256 auth and -sess vectors passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
