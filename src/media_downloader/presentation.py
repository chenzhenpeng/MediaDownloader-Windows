"""UI formatting and redacted diagnostics; no parser SDK dependency."""

from __future__ import annotations

import json

from .platforms import PLATFORMS as CATALOG

PLATFORMS = {key: spec.name for key, spec in CATALOG.items()}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def byte_size(value):
    size = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} B"
        size /= 1024


def progress_text(progress):
    kind = progress.get("kind")
    if kind == "bytes":
        value = byte_size(progress.get("completed_bytes"))
        if progress.get("total_bytes"):
            value += f" / {byte_size(progress['total_bytes'])}"
        if progress.get("speed_bps"):
            value += f" · {byte_size(progress['speed_bps'])}/s"
        if progress.get("eta_seconds") is not None:
            value += f" · 约 {progress['eta_seconds']} 秒"
        return value
    if kind == "count":
        return f"{progress.get('completed_items', 0)} / {progress.get('total_items') or '未知'} 项"
    if progress.get("percent") is not None:
        return f"{progress['percent']:g}%"
    return "等待进度"


def preview_data(task):
    try:
        value = json.loads(task.get("preview") or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def media_description(media):
    kind = {
        "video": "视频",
        "image": "图片",
        "music": "音频",
        "livephoto": "实况照片",
        "ani": "动图",
        "document": "图文正文",
    }.get(media.get("kind"), "媒体")
    parts = [kind, str(media.get("extension", "")).upper()]
    if media.get("width") and media.get("height"):
        parts.append(f"{media['width']} × {media['height']}")
    seconds = media.get("duration_seconds")
    if seconds:
        parts.append(f"{int(seconds) // 60}:{int(seconds) % 60:02d}")
    return " · ".join(part for part in parts if part)


def filtered_tasks(tasks, *, history, query="", state=""):
    return [
        t
        for t in tasks
        if (t["state"] in TERMINAL) == history
        and (not state or t["state"] == state)
        and (
            not query
            or query.casefold() in f"{t['title']} {PLATFORMS.get(t['platform'], '')} {t['id']}".casefold()
        )
    ]


def diagnostic_report(store, engine):
    from . import PROTOCOL, __version__
    from .engine import tool_versions

    return {
        "client": __version__,
        "protocol": PROTOCOL,
        "engine": engine.version,
        "upstream_sha": engine.upstream_sha,
        "tools": tool_versions(engine),
        "tasks": [
            {
                "id": t["id"],
                "state": t["state"],
                "error_code": t.get("error_code", ""),
                "attempts": [
                    {
                        k: a[k]
                        for k in (
                            "id",
                            "action",
                            "state",
                            "engine_version",
                            "upstream_sha",
                            "error_code",
                            "queued_at",
                            "started_at",
                            "finished_at",
                        )
                    }
                    for a in store.attempts(t["id"])
                ],
            }
            for t in store.tasks()
        ],
    }
