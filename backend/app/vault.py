"""Symmetric authenticated encryption at rest for API keys, broker secrets and tokens.

Zero external dependencies: uses PBKDF2-HMAC-SHA256 key derivation, SHA-256 CTR
stream cipher and Encrypt-then-MAC HMAC-SHA256 verification.
Legacy plaintext values (not prefixed with 'enc:v1:') are read transparently
and upgraded to encrypted form the next time they are saved.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Iterable

from . import config

PREFIX = "enc:v1:"
_KEY_CACHE: dict[str, bytes] = {}


def _master_key() -> bytes:
    env_k = os.getenv("EQL_MASTER_KEY", "").strip()
    if env_k:
        return hashlib.sha256(env_k.encode("utf-8")).digest()
    key_file: Path = config.DATA_DIR / ".vault_key"
    kpath = str(key_file)
    if kpath in _KEY_CACHE and key_file.exists():
        return _KEY_CACHE[kpath]
    if key_file.exists():
        raw = key_file.read_bytes().strip()
        if len(raw) >= 32:
            key = hashlib.sha256(raw).digest()
            _KEY_CACHE[kpath] = key
            return key
    key_file.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    key_file.write_bytes(raw)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    key = hashlib.sha256(raw).digest()
    _KEY_CACHE[kpath] = key
    return key


def _derive(master: bytes, nonce: bytes) -> tuple[bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha256", master, nonce, 10_000, dklen=64)
    return dk[:32], dk[32:]


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    ctr = 0
    while len(out) < length:
        out.extend(hashlib.sha256(enc_key + nonce + ctr.to_bytes(4, "big")).digest())
        ctr += 1
    return bytes(out[:length])


def is_encrypted(val: str | None) -> bool:
    return isinstance(val, str) and val.startswith(PREFIX)


def encrypt(text: str | None) -> str:
    if not text:
        return ""
    if is_encrypted(text):
        return text
    raw = text.encode("utf-8")
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = _derive(_master_key(), nonce)
    ks = _keystream(enc_key, nonce, len(raw))
    ct = bytes(a ^ b for a, b in zip(raw, ks))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def decrypt(text: str | None) -> str:
    if not text:
        return ""
    if not is_encrypted(text):
        return text
    try:
        blob = base64.urlsafe_b64decode(text[len(PREFIX):].encode("ascii"))
        if len(blob) < 48:
            return ""
        nonce, tag, ct = blob[:16], blob[16:48], blob[48:]
        enc_key, mac_key = _derive(_master_key(), nonce)
        expected = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return ""
        ks = _keystream(enc_key, nonce, len(ct))
        return bytes(a ^ b for a, b in zip(ct, ks)).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


def encrypt_fields(d: dict, keys: Iterable[str]) -> dict:
    out = dict(d)
    for k in keys:
        if out.get(k):
            out[k] = encrypt(str(out[k]))
    return out


def decrypt_fields(d: dict, keys: Iterable[str]) -> dict:
    out = dict(d)
    for k in keys:
        if out.get(k):
            out[k] = decrypt(str(out[k]))
    return out
