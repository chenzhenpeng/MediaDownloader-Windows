from __future__ import annotations

import time


class ProgressReporter:
    def __init__(self, kind: str, *, clock=time.monotonic):
        self.kind = kind
        self.clock = clock
        self.started = clock()
        self.last_emit: float | None = None
        self.previous_bytes = 0

    def update(self, current: int, total: int) -> dict | None:
        now = self.clock()
        current, total = max(0, current), max(0, total)
        if self.last_emit is not None and now - self.last_emit < 0.2 and (not total or current != total):
            return None
        if self.kind == "bytes" and current < self.previous_bytes:
            self.started = now
        self.last_emit = now
        self.previous_bytes = current
        elapsed = now - self.started
        speed = current / elapsed if self.kind == "bytes" and elapsed > 0.1 else None
        return {
            "phase": "downloading",
            "kind": self.kind,
            "completed_bytes": current if self.kind == "bytes" else None,
            "total_bytes": (total or None) if self.kind == "bytes" else None,
            "completed_items": current if self.kind == "count" else None,
            "total_items": (total or None) if self.kind == "count" else None,
            "percent": min(100, round(current / total * 100, 1)) if total else None,
            "speed_bps": round(speed) if speed else None,
            "eta_seconds": round(max(0, total - current) / speed) if speed and total else None,
        }
