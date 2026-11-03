"""Small shared helpers; no external services or credentials."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone


class ValidationError(ValueError):
    pass


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex[:20]


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def digest(content):
    return hashlib.sha256(content).hexdigest()
