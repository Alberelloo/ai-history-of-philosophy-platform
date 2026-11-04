"""Обезличивание посетителей: необратимый хеш с солью, которая меняется каждые сутки.

По такому хешу можно посчитать уникальных посетителей за день и применить лимиты, но нельзя
восстановить адрес и нельзя связать одного посетителя между разными днями.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime


def visitor_hash(address: str, user_agent: str, moment: datetime, secret: str) -> str:
    salt = hmac.new(
        secret.encode("utf-8"), moment.date().isoformat().encode("utf-8"), hashlib.sha256
    ).digest()
    digest = hmac.new(salt, f"{address}\x00{user_agent}".encode(), hashlib.sha256)
    return digest.hexdigest()[:20]
