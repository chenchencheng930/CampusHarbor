from __future__ import annotations

import uuid
from contextvars import ContextVar


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str:
    return request_id_var.get()
