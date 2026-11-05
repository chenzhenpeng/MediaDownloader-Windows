"""One-command engine process; stdout is exclusively the versioned JSON protocol."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
from pathlib import Path

from . import ENGINE_VERSION, PROTOCOL, UPSTREAM_SHA
from .storage import download_stem, output_directory, valid_output_directory

WIRE = sys.stdout


def emit(command: dict, kind: str, payload: dict):
    if not isinstance(command, dict):
        command = {}
    command["_seq"] = command.get("_seq", 0) + 1
    message = {
        "protocol": PROTOCOL,
        "task_id": command.get("task_id"),
        "attempt_id": command.get("attempt_id"),
        "type": kind,
        "payload": payload,
        "seq": command["_seq"],
    }
    WIRE.write(json.dumps(message, ensure_ascii=False) + "\n")
    WIRE.flush()


def prepare_imports():
    if not getattr(sys, "frozen", False):
        upstream = Path(__file__).resolve().parents[2] / "upstream-ParseHub" / "src"
        sys.path.insert(0, str(upstream))


async def execute(command: dict):
    prepare_imports()
    from .diagnostics import configure_tools

    command["_phase"] = "startup"
    configure_tools()
    from .adapter import ParseHubAdapter

    emit(command, "started", {"engine_version": ENGINE_VERSION, "upstream_sha": UPSTREAM_SHA})
    command["_phase"] = "parsing"
    adapter = ParseHubAdapter(command["source"], proxy=command.get("proxy"), cookie=command.get("cookie"))
    result, preview_model = await adapter.inspect()
    preview = preview_model.to_dict()
    if command["action"] == "inspect":
        from .artwork import fetch_artwork
        from .network import RequestGuard

        preview["thumbnails"] = await fetch_artwork(result, proxy=command.get("proxy"), guard=RequestGuard())
    emit(command, "preview", preview)
    if command["action"] == "inspect":
        emit(command, "ready", preview)
        return

    from .task_files import atomic_json, build_manifest, create_work_directory

    work = create_work_directory(command["output_root"], command["task_id"], command["attempt_id"])

    async def progress(payload):
        emit(command, "progress", payload)

    command["_phase"] = "downloading"
    emit(command, "downloading", {})
    title = result.title or result.content or "未命名作品"
    final = output_directory(
        command["output_root"],
        preview["platform"],
        title,
        command["task_id"],
        command["attempt_id"],
    )
    if not valid_output_directory(command["output_root"], final, command["task_id"], command["attempt_id"]):
        raise ValueError("Invalid output directory")
    # Use the same bounded title for filenames and the post folder.
    folder_title = final.name.rsplit("_", 2)[0]
    result.name = download_stem(folder_title, work)
    downloaded = await adapter.download(
        result,
        work,
        progress,
        selection=command.get("selection"),
        expected_resource_id=command.get("expected_resource_id"),
    )
    files = [p for p in downloaded.output_dir.rglob("*") if p.is_file()]
    from .media_validation import validate_media_payloads

    validate_media_payloads(files)
    from .errors import AppError

    if (
        not downloaded.output_dir.resolve().is_relative_to(work.resolve())
        or not files
        or any(not p.resolve().is_relative_to(work.resolve()) or p.stat().st_size == 0 for p in files)
    ):
        raise AppError("INCOMPLETE_DOWNLOAD", "下载文件缺失或不完整，请重试。", "retry")
    command["_phase"] = "finalizing"
    manifest = await asyncio.to_thread(
        build_manifest, downloaded.output_dir, command, preview, ENGINE_VERSION, UPSTREAM_SHA
    )
    emit(command, "commit_requested", {"final_dir": str(final)})
    if "_approval" in command:
        token = await asyncio.wait_for(asyncio.shield(command["_approval"]), 30)
    else:
        approval = await asyncio.to_thread(sys.stdin.readline)
        token = json.loads(approval) if approval else {}
    if token.get("type") != "authorize_commit" or token.get("attempt_id") != command["attempt_id"]:
        raise RuntimeError("Commit not authorized")
    if not isinstance(token.get("commit_token"), str) or not re.fullmatch(
        r"[0-9a-f]{32}", token["commit_token"]
    ):
        raise RuntimeError("Missing commit token")
    manifest["commit_token"] = token["commit_token"]
    await asyncio.to_thread(atomic_json, downloaded.output_dir / "manifest.json", manifest)
    final.parent.mkdir(exist_ok=True)
    if not valid_output_directory(command["output_root"], final, command["task_id"], command["attempt_id"]):
        raise ValueError("Output directory redirected")
    # On Windows rename fails when the destination already exists; never replace user data.
    os.rename(downloaded.output_dir, final)
    emit(command, "completed", {"final_dir": str(final)})


def main() -> int:
    global ENGINE_VERSION, UPSTREAM_SHA
    # Frozen Python may ignore PYTHONIOENCODING/PYTHONUTF8; the wire is always UTF-8.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    if "--component-dir" in sys.argv:
        index = sys.argv.index("--component-dir")
        from .parser_runtime import activate

        selected = activate(Path(sys.argv[index + 1]), Path(sys.executable).parent / "engine.json")
        ENGINE_VERSION, UPSTREAM_SHA = selected["engine_version"], selected["upstream_sha"]
        del sys.argv[index : index + 2]
    if "--serve" in sys.argv:
        from .engine_server import serve

        with contextlib.redirect_stdout(sys.stderr):
            asyncio.run(serve())
        return 0
    if "--describe" in sys.argv:
        from .diagnostics import configure_tools

        configure_tools()
        from .adapter import capabilities

        platforms = capabilities()

        report = {
            "protocol": PROTOCOL,
            "engine_version": ENGINE_VERSION,
            "upstream_sha": UPSTREAM_SHA,
            "platform_count": sum(item["available"] for item in platforms),
            "capabilities": platforms,
            "frozen": bool(getattr(sys, "frozen", False)),
        }
        WIRE.write(json.dumps(report) + "\n")
        WIRE.flush()
        return 0
    if "--self-test" in sys.argv:
        import argparse

        from .diagnostics import self_test

        parser = argparse.ArgumentParser()
        parser.add_argument("--self-test", action="store_true")
        parser.add_argument("--output", type=Path)
        args = parser.parse_args()
        with contextlib.redirect_stdout(sys.stderr):
            report = self_test(ENGINE_VERSION, args.output)
        WIRE.write(json.dumps(report, ensure_ascii=False) + "\n")
        WIRE.flush()
        return 0
    command = {}
    try:
        line = sys.stdin.buffer.readline(1024 * 1024 + 1)
        if len(line) > 1024 * 1024:
            raise ValueError("Command exceeds size limit")
        command = json.loads(line)
        from .contracts import validate_command

        validate_command(command, PROTOCOL)
        with contextlib.redirect_stdout(sys.stderr):
            asyncio.run(execute(command))
    except BaseException as exc:
        # Third-party exception strings may contain Cookie or signed URLs.
        from .errors import classify_error

        emit(
            command,
            "failed",
            classify_error(
                exc, command.get("_phase", "parsing") if isinstance(command, dict) else "parsing"
            ).to_dict(),
        )
        return 1
    return 0


if __name__ == "__main__":
    # -m executes this module as __main__. Reusing it prevents engine_server from
    # importing a second worker while stdout is redirected to the diagnostic stream.
    sys.modules[f"{__package__}.worker"] = sys.modules[__name__]
    raise SystemExit(main())
