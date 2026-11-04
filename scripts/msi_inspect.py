"""Read Windows Installer architecture and native action headers without installing."""

from __future__ import annotations

import ctypes as c
import json
import struct
import sys
from ctypes import wintypes as w

msi = c.WinDLL("msi", use_last_error=True)
handle = w.UINT
msi.MsiOpenDatabaseW.argtypes = [w.LPCWSTR, w.LPCWSTR, c.POINTER(handle)]
msi.MsiGetSummaryInformationW.argtypes = [handle, w.LPCWSTR, w.UINT, c.POINTER(handle)]
msi.MsiSummaryInfoGetPropertyW.argtypes = [
    handle,
    w.UINT,
    c.POINTER(w.UINT),
    c.POINTER(c.c_int),
    c.c_void_p,
    w.LPWSTR,
    c.POINTER(w.DWORD),
]
msi.MsiDatabaseOpenViewW.argtypes = [handle, w.LPCWSTR, c.POINTER(handle)]
msi.MsiViewExecute.argtypes = [handle, handle]
msi.MsiViewFetch.argtypes = [handle, c.POINTER(handle)]
msi.MsiRecordGetStringW.argtypes = [handle, w.UINT, w.LPWSTR, c.POINTER(w.DWORD)]
msi.MsiRecordGetInteger.argtypes = [handle, w.UINT]
msi.MsiRecordReadStream.argtypes = [handle, w.UINT, c.c_void_p, c.POINTER(w.DWORD)]
msi.MsiCloseHandle.argtypes = [handle]


def checked(code):
    if code:
        raise OSError(f"Windows Installer error {code}")


def string(record, field):
    buffer, length = c.create_unicode_buffer(2048), w.DWORD(2048)
    checked(msi.MsiRecordGetStringW(record, field, buffer, c.byref(length)))
    return buffer.value


def inspect(path):
    summary, database = handle(), handle()
    checked(msi.MsiGetSummaryInformationW(0, str(path), 0, c.byref(summary)))
    try:
        value, length, kind, integer = c.create_unicode_buffer(512), w.DWORD(512), w.UINT(), c.c_int()
        checked(
            msi.MsiSummaryInfoGetPropertyW(
                summary, 7, c.byref(kind), c.byref(integer), None, value, c.byref(length)
            )
        )
        template = value.value
    finally:
        msi.MsiCloseHandle(summary)
    checked(msi.MsiOpenDatabaseW(str(path), None, c.byref(database)))

    def rows(query):
        view = handle()
        checked(msi.MsiDatabaseOpenViewW(database, query, c.byref(view)))
        try:
            checked(msi.MsiViewExecute(view, 0))
            while True:
                record = handle()
                code = msi.MsiViewFetch(view, c.byref(record))
                if code == 259:
                    break
                checked(code)
                try:
                    yield record
                finally:
                    msi.MsiCloseHandle(record)
        finally:
            msi.MsiCloseHandle(view)

    try:
        properties = {
            string(row, 1): string(row, 2) for row in rows("SELECT `Property`, `Value` FROM `Property`")
        }
        attributes = [msi.MsiRecordGetInteger(row, 1) for row in rows("SELECT `Attributes` FROM `Component`")]
        actions = []
        for row in rows("SELECT `Name`, `Data` FROM `Binary`"):
            buffer, length = c.create_string_buffer(4096), w.DWORD(4096)
            checked(msi.MsiRecordReadStream(row, 2, buffer, c.byref(length)))
            data = buffer.raw[: length.value]
            if data[:2] == b"MZ":
                offset = struct.unpack_from("<I", data, 0x3C)[0]
                machine = struct.unpack_from("<H", data, offset + 4)[0]
                actions.append({"name": string(row, 1), "machine": hex(machine)})
        assert template.startswith("x64;")
        assert attributes and all(value & 0x100 for value in attributes)
        assert all(action["machine"] == "0x8664" for action in actions)
        return {
            "template": template,
            "product_code": properties["ProductCode"],
            "product_version": properties["ProductVersion"],
            "components_x64": len(attributes),
            "native_actions": actions,
        }
    finally:
        msi.MsiCloseHandle(database)


if __name__ == "__main__":
    print(json.dumps(inspect(sys.argv[1]), indent=2))
