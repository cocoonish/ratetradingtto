"""Accounts and sign-in: what a password and a session are, and nothing else.

A password is kept only as a salted PBKDF2-SHA256 hash (``pbkdf2_sha256$<rounds>$<salt hex>$<hash hex>``: the
number of rounds travels with the hash, so it can be raised later without locking anybody out).  A session is a
random token the browser keeps in an HttpOnly cookie; the database keeps only its SHA-256, so a copy of the
database does not sign anybody in.  Python's own library does all of it - nothing to install.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import secrets
from typing import Optional

#: PBKDF2-SHA256 rounds of a new hash (~0.5 s on a desk PC: slow for a guesser, unnoticed at a sign-in)
ROUNDS = 600_000
#: how long a sign-in lasts (days); signing out or a closed account ends it earlier
SESSION_DAYS = 7
#: wrong passwords in a row after which a name is locked, and for how long (seconds)
MAX_FAILED = 5
LOCK_SECONDS = 60
#: the shortest and the longest password accepted
MIN_PASSWORD = 8
MAX_PASSWORD = 200

#: the name of the cookie that carries the session token
COOKIE = "tto_oturum"

ROLES = ("admin", "user")
STATUSES = ("active", "pending", "disabled")


def hash_password(password: str, rounds: Optional[int] = None, salt: Optional[bytes] = None) -> str:
    rounds = int(rounds or ROUNDS)
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256$%d$%s$%s" % (rounds, salt.hex(), digest.hex())


def check_password(password: str, stored: Optional[str]) -> bool:
    """Does ``password`` match the stored hash?  ``False`` for an account without a password."""
    try:
        algo, rounds, salt, want = str(stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), bytes.fromhex(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), want)


def password_problem(password: Optional[str]) -> Optional[str]:
    """Why a new password is not accepted (``None``: it is)."""
    pw = str(password or "")
    if len(pw) < MIN_PASSWORD:
        return "şifre en az %d karakter olmalı" % MIN_PASSWORD
    if len(pw) > MAX_PASSWORD:
        return "şifre en fazla %d karakter olabilir" % MAX_PASSWORD
    if not pw.strip():
        return "şifre yalnızca boşluk olamaz"
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def stamp(when: _dt.datetime) -> str:
    return when.replace(microsecond=0).isoformat(sep=" ")


def is_local(host: Optional[str]) -> bool:
    """A request from the dashboard's own computer (the first administrator is created only from there)."""
    return str(host or "") in ("127.0.0.1", "::1", "localhost")
