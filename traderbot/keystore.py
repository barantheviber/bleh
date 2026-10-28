"""Protecting broker keys at rest.

On Windows the key is encrypted with DPAPI (CryptProtectData), so only the
same Windows user on the same machine can decrypt it; settings.json then holds
"dpapi:<base64>". Elsewhere the value is stored as "plain:<base64>" (encoded,
not encrypted) and the settings file is made readable by its owner only.
"""

import base64
import sys

if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _crypt(fn, data):
        blob_in, _keep = _blob(data)
        blob_out = _Blob()
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
            raise OSError("DPAPI call failed (error %d)" % ctypes.GetLastError())
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _protect(data):
        return _crypt(ctypes.windll.crypt32.CryptProtectData, data)

    def _unprotect(data):
        return _crypt(ctypes.windll.crypt32.CryptUnprotectData, data)
else:
    _protect = _unprotect = None


def protect(text):
    if not text:
        return ""
    raw = text.encode("utf-8")
    if _protect is not None:
        return "dpapi:" + base64.b64encode(_protect(raw)).decode("ascii")
    return "plain:" + base64.b64encode(raw).decode("ascii")


def unprotect(value):
    """The original text, or "" if the value is empty or cannot be read (a
    settings file copied from another Windows user, for example)."""
    if not value:
        return ""
    try:
        kind, payload = value.split(":", 1)
        raw = base64.b64decode(payload)
        if kind == "dpapi":
            if _unprotect is None:
                return ""
            raw = _unprotect(raw)
        elif kind != "plain":
            return ""
        return raw.decode("utf-8")
    except (ValueError, OSError, UnicodeDecodeError):
        return ""


def mask(text):
    """'PKAB...WXYZ' style display of a key, never the whole thing."""
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return text[:4] + "…" + text[-4:]
