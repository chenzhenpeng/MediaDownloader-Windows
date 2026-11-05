"""Persistent single-job worker with cooperative control and heartbeats."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading


def stdin_chunks():
    if sys.platform != "win32":
        while chunk := os.read(sys.stdin.fileno(), 65536):
            yield chunk
        return
    # CRT _read holds stdin's descriptor lock while waiting. Native libraries
    # (including NumPy) inspect stdin during import and can deadlock on that lock.
    # Read the Windows pipe directly without taking the CRT descriptor lock.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    read_file = ctypes.WinDLL("kernel32", use_last_error=True).ReadFile
    read_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    buffer = ctypes.create_string_buffer(65536)
    count = wintypes.DWORD()
    while read_file(handle, buffer, len(buffer), ctypes.byref(count), None):
        if not count.value:
            return
        yield buffer.raw[: count.value]


async def serve(*, execute=None):
    from . import worker
    from .contracts import validate_command
    from .diagnostics import configure_tools
    from .errors import classify_error

    configure_tools()
    loop = asyncio.get_running_loop()
    inbox: asyncio.Queue = asyncio.Queue()
    current: dict | None = None
    execution: asyncio.Task | None = None
    shutdown_requested = False
    server = {}

    def read_commands():
        buffer = b""
        try:
            for chunk in stdin_chunks():
                buffer += chunk
                if len(buffer) > 1024 * 1024 and b"\n" not in buffer:
                    break
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    loop.call_soon_threadsafe(inbox.put_nowait, line)
        except (OSError, RuntimeError):
            pass
        finally:
            try:
                loop.call_soon_threadsafe(inbox.put_nowait, None)
            except RuntimeError:
                pass

    threading.Thread(target=read_commands, name="engine-stdin", daemon=True).start()
    worker.emit(
        server,
        "worker_ready",
        {"engine_version": worker.ENGINE_VERSION, "upstream_sha": worker.UPSTREAM_SHA, "pid": os.getpid()},
    )

    async def run_command(command):
        nonlocal current, execution
        try:
            await (execute or worker.execute)(command)
        except asyncio.CancelledError:
            worker.emit(command, "cancelled", {})
        except Exception as exc:
            worker.emit(command, "failed", classify_error(exc, command.get("_phase", "parsing")).to_dict())
        finally:
            worker.emit(command, "idle", {})
            command.clear()
            current, execution = None, None
            if shutdown_requested:
                inbox.put_nowait(None)

    async def heartbeat():
        while True:
            await asyncio.sleep(2)
            worker.emit(
                current if current is not None else server,
                "heartbeat",
                {"phase": current.get("_phase", "idle") if current else "idle"},
            )

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        while True:
            line = await inbox.get()
            if line is None:
                if execution:
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                break
            try:
                command = json.loads(line)
                if not isinstance(command, dict):
                    raise ValueError("Invalid command")
                kind = command.get("type")
                if kind == "shutdown":
                    shutdown_requested = True
                    if execution is None:
                        break
                    if not current.get("_commit_authorized"):
                        execution.cancel()
                elif kind in {"cancel", "authorize_commit"}:
                    if (
                        current is None
                        or command.get("task_id") != current.get("task_id")
                        or command.get("attempt_id") != current.get("attempt_id")
                    ):
                        continue
                    if kind == "cancel":
                        if not current.get("_commit_authorized"):
                            execution.cancel()
                    elif not current["_approval"].done():
                        current["_commit_authorized"] = True
                        current["_approval"].set_result(command)
                else:
                    validate_command(command, worker.PROTOCOL)
                    if execution is not None:
                        raise ValueError("Worker is busy")
                    current = command
                    current["_approval"] = loop.create_future()
                    execution = asyncio.create_task(run_command(command))
                    await asyncio.sleep(0)  # Enter try/finally before a queued immediate cancel.
            except Exception as exc:
                worker.emit({}, "control_error", {"code": "INVALID_COMMAND", "message": type(exc).__name__})
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
