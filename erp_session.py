from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path
from typing import Any


SESSION_FILE = Path(__file__).resolve().parent / ".erp_session.bin"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("系统网页登录会话目前只支持 Windows 加密存储")
    source, source_buffer = _blob_from_bytes(data)
    target = _DataBlob()
    description = "LEEDIS weekly report session"
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(target),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
        del source_buffer


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("系统网页登录会话目前只支持 Windows 加密存储")
    source, source_buffer = _blob_from_bytes(data)
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(target),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
        del source_buffer


def save_session(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    SESSION_FILE.write_bytes(_protect(serialized))


def load_session() -> dict[str, Any] | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(_unprotect(SESSION_FILE.read_bytes()).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def delete_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
