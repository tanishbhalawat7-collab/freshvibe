from __future__ import annotations

from fastapi import HTTPException


def api_error(status: int, code: str, message: str, hint: str = "", **extra) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message, "hint": hint, **extra})
