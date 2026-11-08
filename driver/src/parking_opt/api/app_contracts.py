"""Shared FastAPI contract constants for web-v2 routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from parking_opt.api.models import ErrorResponse

ERROR_RESPONSES = {
    500: {"model": ErrorResponse, "description": "Unexpected internal failure"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Capability conflict"},
    422: {"model": ErrorResponse, "description": "Contract validation failed"},
    503: {"model": ErrorResponse, "description": "Data source unavailable"},
}
SessionIdHeader = Annotated[
    str | None,
    Header(
        alias="X-Session-ID",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description="Optional synthetic driver-session context. It is not an authentication credential.",
    ),
]
RequiredSessionIdHeader = Annotated[
    str,
    Header(
        alias="X-Session-ID",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description="Required synthetic driver-session context. It is not an authentication credential.",
    ),
]
