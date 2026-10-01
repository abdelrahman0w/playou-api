import base64
import hashlib
import secrets


def make_verifier() -> str:
    return secrets.token_urlsafe(48)


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()

    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
