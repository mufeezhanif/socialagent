import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from app.config import settings

_password_hash = PasswordHash.recommended()
SESSION_COOKIE = "session"
SESSION_TTL_S = 7 * 24 * 3600
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        return False


def create_session_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + SESSION_TTL_S, "typ": "session"}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_session_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "session":
        return None
    return payload.get("sub")


def create_state_token(user_id: str, purpose: str, ttl_s: int = 900) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + ttl_s, "typ": purpose, "n": secrets.token_hex(4)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_state_token(token: str, purpose: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload.get("sub") if payload.get("typ") == purpose else None


@lru_cache
def _fernet() -> Fernet:
    raw = settings.token_encryption_key or settings.jwt_secret
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        # Any string works: derive a valid Fernet key from it.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_media(path: str | Path, ttl_s: int = 6 * 3600) -> str:
    """Signed, expiring token for a file inside media_dir."""
    rel = Path(path).resolve().relative_to(Path(settings.media_dir).resolve()).as_posix()
    body = _b64(json.dumps({"p": rel, "e": int(time.time()) + ttl_s}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(settings.media_signing_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def media_url(path: str | Path, ttl_s: int = 6 * 3600) -> str:
    return f"{settings.app_base_url.rstrip('/')}/media/{sign_media(path, ttl_s)}"


def verify_media_token(token: str) -> Path | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64(hmac.new(settings.media_signing_secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("e", 0)) < time.time():
        return None
    root = Path(settings.media_dir).resolve()
    target = (root / data["p"]).resolve()
    if root not in target.parents:
        return None
    return target if target.is_file() else None


def new_link_code() -> str:
    return "LINK-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def internal_secret_ok(value: str | None) -> bool:
    return bool(value) and hmac.compare_digest(value, settings.internal_shared_secret)
