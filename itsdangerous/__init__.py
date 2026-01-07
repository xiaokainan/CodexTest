from __future__ import annotations

import base64
import hmac
import hashlib
import time
from typing import Optional

from .exc import BadSignature


class TimestampSigner:
    def __init__(self, secret_key: str) -> None:
        self._secret = secret_key.encode("utf-8")

    def sign(self, value: bytes) -> bytes:
        timestamp = str(int(time.time())).encode("utf-8")
        signature = self._get_signature(value, timestamp)
        return b".".join([value, timestamp, signature])

    def unsign(self, signed_value: bytes, max_age: Optional[int] = None) -> bytes:
        try:
            value, timestamp, signature = signed_value.split(b".", 2)
        except ValueError as exc:
            raise BadSignature("Invalid signature format") from exc

        expected = self._get_signature(value, timestamp)
        if not hmac.compare_digest(signature, expected):
            raise BadSignature("Signature does not match")

        if max_age is not None:
            age = int(time.time()) - int(timestamp.decode("utf-8"))
            if age > max_age:
                raise BadSignature("Signature has expired")

        return value

    def _get_signature(self, value: bytes, timestamp: bytes) -> bytes:
        digest = hmac.new(self._secret, msg=value + b"." + timestamp, digestmod=hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).strip(b"=")


__all__ = ["BadSignature", "TimestampSigner"]
