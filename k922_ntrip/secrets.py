"""Small OS-backed secret storage helpers.

Windows uses user-scoped DPAPI. Other platforms use the configured system
keyring, so passwords are never written as cleartext by ConfigStore.
"""

from __future__ import annotations

import base64
import ctypes
import os
import uuid
from ctypes import wintypes


SERVICE_NAME = "K922 NTRIP Client"
DPAPI_PREFIX = "dpapi-v1:"
KEYRING_MARKER = "keyring-v1"
KEYRING_PREFIX = "keyring-v1:"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _make_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _protect_windows(value: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    protect.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL

    source, source_buffer = _make_blob(value)
    result = _DataBlob()
    if not protect(
        ctypes.byref(source),
        "K922 NTRIP Client credential",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        local_free(ctypes.cast(result.pbData, wintypes.HLOCAL))
        del source_buffer


def _unprotect_windows(value: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    unprotect.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL

    source, source_buffer = _make_blob(value)
    result = _DataBlob()
    if not unprotect(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        local_free(ctypes.cast(result.pbData, wintypes.HLOCAL))
        del source_buffer


def protect_password(password: str, context: str) -> str:
    if os.name == "nt":
        encrypted = _protect_windows(password.encode("utf-8"))
        return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")

    try:
        import keyring

        key_id = uuid.uuid4().hex
        keyring.set_password(SERVICE_NAME, f"{context}|{key_id}", password)
    except Exception as exc:
        raise RuntimeError(f"无法访问系统凭据库：{exc}") from exc
    return KEYRING_PREFIX + key_id


def reveal_password(reference: str, context: str) -> str:
    if reference.startswith(DPAPI_PREFIX):
        if os.name != "nt":
            raise RuntimeError("该密码由 Windows 用户凭据保护，需在原 Windows 用户环境中读取")
        encoded = reference[len(DPAPI_PREFIX) :]
        try:
            encrypted = base64.b64decode(encoded, validate=True)
            return _unprotect_windows(encrypted).decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"无法解密已保存的 CORS 密码：{exc}") from exc

    if reference == KEYRING_MARKER:
        keyring_user = context  # Compatibility with the first keyring format.
    elif reference.startswith(KEYRING_PREFIX):
        key_id = reference[len(KEYRING_PREFIX) :]
        if not key_id or any(character not in "0123456789abcdef" for character in key_id):
            raise RuntimeError("系统凭据库引用格式无效")
        keyring_user = f"{context}|{key_id}"
    else:
        raise RuntimeError("密码保护格式不受支持")

    try:
        import keyring

        password = keyring.get_password(SERVICE_NAME, keyring_user)
    except Exception as exc:
        raise RuntimeError(f"无法读取系统凭据库：{exc}") from exc
    if password is None:
        raise RuntimeError("系统凭据库中找不到此配置对应的密码")
    return password


def delete_password(context: str, reference: str | None = None) -> None:
    if os.name == "nt" or not reference:
        return
    if reference == KEYRING_MARKER:
        keyring_user = context
    elif reference.startswith(KEYRING_PREFIX):
        key_id = reference[len(KEYRING_PREFIX) :]
        keyring_user = f"{context}|{key_id}"
    else:
        return
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(SERVICE_NAME, keyring_user)
        except PasswordDeleteError:
            pass
    except Exception as exc:
        raise RuntimeError(f"无法清理系统凭据库：{exc}") from exc
