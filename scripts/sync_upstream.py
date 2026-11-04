"""Prepare a candidate from upstream Git, replay pinned patches, never execute upstream code."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tomllib
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from media_downloader import UPSTREAM_SHA
from media_downloader.update_archive import no_reparse, safe_relative

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/z-mio/ParseHub.git"


def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", str(repository), *arguments])


def apply_reviewed_patch(candidate, patch):
    # The candidate lives inside the application checkout. Stop Git discovering
    # that outer repository, otherwise paths can be skipped or refer to its tree.
    environment = dict(os.environ, GIT_CEILING_DIRECTORIES=str(candidate.parent.resolve()))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        environment.pop(name, None)
    check = subprocess.run(
        ["git", "apply", "--check", str(patch.resolve())], cwd=candidate, env=environment, capture_output=True
    )
    if check.returncode:
        return False
    subprocess.run(["git", "apply", str(patch.resolve())], cwd=candidate, env=environment, check=True)
    return True


def latest_release(repository):
    request = urllib.request.Request(
        "https://api.github.com/repos/z-mio/ParseHub/releases/latest",
        headers={"User-Agent": "MediaDownloader-Upstream-Watch", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read(131073))
        tag = data["tag_name"]
        subprocess.run(["git", "check-ref-format", "refs/tags/" + tag], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repository), "fetch", "origin", "refs/tags/" + tag], check=True)
        sha = git(repository, "rev-parse", "FETCH_HEAD^{commit}").decode().strip()
        return {"tag": tag, "sha": sha, "published_at": data.get("published_at")}
    except urllib.error.HTTPError as exc:
        return None if exc.code == 404 else {"check_error": f"HTTP_{exc.code}"}
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return {"check_error": "RELEASE_CHECK_FAILED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, help="Existing local Git object database, for offline validation"
    )
    parser.add_argument("--sha", help="Exact candidate SHA; otherwise fetch upstream default branch")
    parser.add_argument(
        "--apply", action="store_true", help="Apply a successful candidate to the working tree"
    )
    parser.add_argument("--report", type=Path, default=ROOT / "review/upstream-candidate.json")
    args = parser.parse_args()
    if args.sha and not re.fullmatch("[0-9a-f]{40}", args.sha):
        raise ValueError("--sha requires a full lowercase commit SHA")
    repository = args.source or ROOT / ".cache/upstream-sync"
    if args.source is None:
        if not repository.exists():
            subprocess.run(
                ["git", "clone", "--bare", "--filter=blob:none", UPSTREAM, str(repository)], check=True
            )
        subprocess.run(["git", "-C", str(repository), "fetch", "--prune", "origin", "HEAD"], check=True)
    sha = git(repository, "rev-parse", f"{args.sha or 'FETCH_HEAD'}^{{commit}}").decode().strip()
    default_head, release = sha, None
    if args.source is None and args.sha is None:
        release = latest_release(repository)
        if release and release.get("sha"):
            covered = (
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repository),
                        "merge-base",
                        "--is-ancestor",
                        release["sha"],
                        default_head,
                    ],
                    capture_output=True,
                ).returncode
                == 0
            )
            processed = (
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repository),
                        "merge-base",
                        "--is-ancestor",
                        release["sha"],
                        UPSTREAM_SHA,
                    ],
                    capture_output=True,
                ).returncode
                == 0
            )
            if not covered and not processed:
                sha = release["sha"]
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise ValueError("Invalid upstream SHA")
    catalog = json.loads((ROOT / "patches/parsehub/patchset.json").read_text(encoding="utf-8"))
    candidate = ROOT / ".local/upstream-candidates" / (sha[:12] + "-" + uuid.uuid4().hex[:8])
    candidate.mkdir(parents=True)
    raw = git(repository, "archive", "--format=zip", sha)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 100 * 1024**2:
            raise ValueError("Candidate source exceeds budget")
        for item in archive.infolist():
            parts = safe_relative(item.filename)
            if any(part.casefold() == ".git" for part in parts):
                raise ValueError("Upstream archive must not contain Git administrative directories")
            destination = candidate.joinpath(*parts)
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                if item.external_attr >> 16 & 0o170000 == 0o120000:
                    raise ValueError("Symlink in upstream source")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(item))
    report = {
        "base_sha": UPSTREAM_SHA,
        "candidate_sha": sha,
        "default_head": default_head,
        "latest_release": release,
        "changed": sha != UPSTREAM_SHA,
        "patches_applied": [],
        "ready": False,
        "candidate_directory": str(candidate.relative_to(ROOT)),
        "note": "Candidate only; refresh lock and validate tests, builds and live samples before signing.",
    }
    failed = False
    for item in catalog["patches"]:
        patch = ROOT / "patches/parsehub" / item["file"]
        if hashlib.sha256(patch.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Patch hash mismatch")
        if not apply_reviewed_patch(candidate, patch):
            report["blocked_patch"] = item["file"]
            failed = True
            break
        report["patches_applied"].append(item["file"])
    if not failed:
        original = tomllib.loads((ROOT / "upstream-ParseHub/pyproject.toml").read_text(encoding="utf-8"))
        updated = tomllib.loads((candidate / "pyproject.toml").read_text(encoding="utf-8"))
        report["dependencies_changed"] = (
            original["project"]["dependencies"] != updated["project"]["dependencies"]
        )
        report["version_before"] = original["project"]["version"]
        report["version_after"] = updated["project"]["version"]
        report["changed_files"] = (
            git(repository, "diff", "--name-only", UPSTREAM_SHA, sha).decode().splitlines()
        )
        report["dependency_metadata_changed"] = any(
            original.get(key) != updated.get(key) for key in ("build-system", "dependency-groups")
        ) or any(
            original["project"].get(key) != updated["project"].get(key)
            for key in ("dependencies", "optional-dependencies", "requires-python")
        )
        report["interface_files_changed"] = [
            name
            for name in report["changed_files"]
            if name.startswith("src/parsehub/types/")
            or name in {"src/parsehub/__init__.py", "src/parsehub/parsers/base/base.py", "pyproject.toml"}
        ]
        report["ready"] = True
        if args.apply and report["changed"]:
            vendor = ROOT / "upstream-ParseHub"
            no_reparse(vendor)
            # Delete only explicitly named old tracked files, within the vendor directory.
            old_files = git(repository, "ls-tree", "-r", "--name-only", UPSTREAM_SHA).decode().splitlines()
            for relative in old_files:
                if relative == "uv.lock":
                    continue
                destination = vendor.joinpath(*safe_relative(relative))
                no_reparse(destination)
                if (
                    destination.resolve().is_relative_to(vendor.resolve())
                    and not (candidate / relative).exists()
                ):
                    destination.unlink(missing_ok=True)
            for source in candidate.rglob("*"):
                if source.is_file() and source.name != "uv.lock":
                    relative = source.relative_to(candidate)
                    destination = vendor / relative
                    no_reparse(destination)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            version_file = ROOT / "src/media_downloader/__init__.py"
            text = version_file.read_text(encoding="utf-8")
            text = re.sub(r'UPSTREAM_SHA = "[0-9a-f]{40}"', f'UPSTREAM_SHA = "{sha}"', text)
            version = datetime.now(UTC).strftime("%Y.%m.%d.") + sha[:8]
            text = re.sub(r'ENGINE_VERSION = "[^"]+"', f'ENGINE_VERSION = "{version}"', text)
            version_file.write_text(text, encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "candidate_directory"}))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
