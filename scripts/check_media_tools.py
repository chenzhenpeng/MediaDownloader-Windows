"""Exercise prebuilt FFmpeg tools with muxing, HLS and full decoding."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--yt-dlp", type=Path)
    args = parser.parse_args()
    tools = args.tools.resolve()
    output = ROOT / ".local/media-tools-check" / str(time.time_ns())
    output.mkdir(parents=True)
    ffmpeg, ffprobe = tools / "ffmpeg.exe", tools / "ffprobe.exe"
    env = dict(os.environ, PATH=str(Path(os.environ["SystemRoot"]) / "System32"))

    def run(program, *arguments):
        result = subprocess.run(
            [str(program), *map(str, arguments)],
            cwd=output,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            creationflags=0x08000000,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2000:])
        return result.stdout

    def ff(*arguments):
        return run(ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments)

    ff("-f", "lavfi", "-i", "testsrc2=size=128x72:rate=24:duration=2", "-c:v", "libx264", "video.mp4")
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", "audio.m4a")
    ff("-i", "video.mp4", "-i", "audio.m4a", "-c", "copy", "-movflags", "+faststart", "merged.mp4")
    ff("-i", "merged.mp4", "-c", "copy", "-hls_time", "1", "-hls_list_size", "0", "sample.m3u8")
    ff("-i", "sample.m3u8", "-c", "copy", "hls.mp4")
    if args.yt_dlp:

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass

        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(output))
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            run(
                args.yt_dlp.resolve(),
                "--ignore-config",
                "--proxy",
                "",
                "--quiet",
                "--no-warnings",
                "--ffmpeg-location",
                tools,
                "--fixup",
                "force",
                "--merge-output-format",
                "mp4",
                "-o",
                "ytdlp.mp4",
                f"http://127.0.0.1:{server.server_port}/sample.m3u8",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    checks = {}
    for name in ["merged.mp4", "hls.mp4"] + (["ytdlp.mp4"] if args.yt_dlp else []):
        metadata = json.loads(
            run(ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", name)
        )
        streams = metadata["streams"]
        assert {s["codec_name"] for s in streams} == {"h264", "aac"}
        video = next(s for s in streams if s["codec_type"] == "video")
        assert (video["width"], video["height"]) == (128, 72)
        assert 1.9 <= float(metadata["format"]["duration"]) <= 2.2
        ff("-xerror", "-i", name, "-f", "null", "-")
        checks[name] = {"mux_probe_decode": True, "bytes": (output / name).stat().st_size}
    report = {
        "passed": True,
        "tools": {
            p.name: {
                "sha256": hashlib.file_digest(p.open("rb"), "sha256").hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in (ffmpeg, ffprobe)
        },
        "checks": checks,
    }
    target = ROOT / "review/media-tools-acceptance.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
