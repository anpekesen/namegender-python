"""Webhook signature check.

Pass the body exactly as received (``request.body`` in Django,
``request.get_data()`` in Flask, ``await request.body()`` in FastAPI). Parsing
the JSON and serialising it again changes the bytes, and the signature no
longer matches.
"""
import hashlib
import hmac
import json
import time

from .client import NameGenderError


class WebhookVerificationError(NameGenderError):
    """The request is not a genuine NameGender webhook. Answer it with 400."""


def verify(payload, signature_header, secret, tolerance=300, now=None):
    """Check ``NameGender-Signature`` and return the parsed event.

    ``payload`` is the raw body as bytes or str. During a secret rotation the
    header carries two ``v1`` values; either one matching is enough.
    """
    if not secret:
        raise ValueError("secret is required")
    if not signature_header:
        raise WebhookVerificationError("Missing NameGender-Signature header")

    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    elif not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be the raw request body (bytes or str)")

    timestamp = None
    signatures = []
    for part in str(signature_header).split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.isdigit():
            timestamp = int(value)
        elif key == "v1" and value:
            signatures.append(value)

    if timestamp is None or not signatures:
        raise WebhookVerificationError("Malformed NameGender-Signature header")

    if abs((time.time() if now is None else now) - timestamp) > tolerance:
        raise WebhookVerificationError("Webhook timestamp is outside the tolerance window")

    expected = hmac.new(secret.encode("utf-8"), str(timestamp).encode() + b"." + bytes(payload), hashlib.sha256).hexdigest()

    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise WebhookVerificationError("Webhook signature does not match")

    return json.loads(payload)
