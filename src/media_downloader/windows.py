"""Small Windows boundary: DPAPI credentials and kill-on-close process jobs."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as w


class Blob(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI requires Windows")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [w.HLOCAL]
    kernel.LocalFree.restype = w.HLOCAL
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        w.DWORD,
        ctypes.POINTER(Blob),
    ]
    func.restype = w.BOOL
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, w.HLOCAL))


def protect(text: str) -> bytes:
    return _crypt(text.encode("utf-8"), False)


def unprotect(data: bytes) -> str:
    return _crypt(data, True).decode("utf-8")


def set_window_dark_mode(handle: int, dark: bool):
    """Keep the system title bar and Snap behavior, while matching the app theme."""
    if os.name != "nt":
        return
    try:
        dwm = ctypes.WinDLL("dwmapi")
        setter = dwm.DwmSetWindowAttribute
        setter.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
        setter.restype = ctypes.c_long
        value = w.BOOL(dark)
        setter(handle, 20, ctypes.byref(value), ctypes.sizeof(value))
    except OSError:
        pass


class BasicLimit(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", w.DWORD),
        ("min_working", ctypes.c_size_t),
        ("max_working", ctypes.c_size_t),
        ("active_limit", w.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class IOCounts(ctypes.Structure):
    _fields_ = [
        (n, ctypes.c_uint64) for n in ("read_ops", "write_ops", "other_ops", "read", "write", "other")
    ]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimit),
        ("io", IOCounts),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class ProcessJob:
    def __init__(self, pid: int):
        self.handle = None
        if os.name != "nt":
            return
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenProcess.restype = w.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        handle = self.api.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle = handle
        info = ExtendedLimit()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.api.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = self.api.OpenProcess(0x0001 | 0x0100, False, pid)
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self.api.AssignProcessToJobObject(handle, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.api.CloseHandle(process)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
