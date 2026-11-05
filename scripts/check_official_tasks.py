"""Exercise the real task service in a fresh, isolated database and output root."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    from PySide6.QtCore import QCoreApplication

    from media_downloader import ENGINE_VERSION, UPSTREAM_SHA
    from media_downloader.engine import Engine
    from media_downloader.official_paths import candidate_python
    from media_downloader.service import TaskService
    from media_downloader.storage import Store

    parser = argparse.ArgumentParser()
    runtimes = parser.add_mutually_exclusive_group(required=True)
    runtimes.add_argument("--runtime", type=Path)
    runtimes.add_argument("--environment-root", type=Path)
    runtimes.add_argument("--production-runtime", type=Path)
    parser.add_argument("--trust-file", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tools-directory", type=Path, required=True)
    parser.add_argument("--expect-auth-required", action="store_true")
    args = parser.parse_args()
    if args.production_runtime:
        args.runtime = args.production_runtime
    authenticated = False
    parser_version = "2.4.0"
    if args.environment_root:
        if not args.trust_file:
            raise ValueError("Authenticated selection requires a trust file")
        from media_downloader.official_trust import VerifiedOfficialEnvironments
        from media_downloader.update_contracts import load_trust

        environments = VerifiedOfficialEnvironments(
            args.environment_root, load_trust(args.trust_file, allow_local=True)
        )
        # Verify signature and every selected file before launching its Python.
        args.runtime = environments.resolve()
        if args.runtime is None:
            raise ValueError("No authenticated environment selected")
        parser_version = environments.version(args.runtime.name)
        authenticated = True
    root = args.root.absolute()
    if root.exists():
        raise ValueError("Task check requires a new isolated directory")
    root.mkdir(parents=True)
    output = root / "downloads"
    output.mkdir()
    app = QCoreApplication.instance() or QCoreApplication([])
    store = Store(root / "tasks.sqlite3")
    arguments = (
        "-B",
        "-I",
        str(ROOT / "scripts/run_official_worker.py"),
        "--experimental-official",
        "--tools-directory",
        str(args.tools_directory.resolve()),
        "--expected-parsehub-version",
        parser_version,
    )
    engine = Engine(
        ENGINE_VERSION,
        UPSTREAM_SHA,
        str(candidate_python(args.runtime.resolve())),
        arguments,
        parser_version=parser_version,
        component="official-experimental",
    )
    if args.production_runtime:
        from media_downloader.engine import resolve_engine

        engine = resolve_engine(args.production_runtime.resolve())
    service = TaskService(store, engine=engine, max_workers=1)
    states = []

    def wait_for(task_id, terminal, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            task = store.get(task_id)
            if not states or states[-1] != task["state"]:
                states.append(task["state"])
            if task["state"] in terminal and not service.running:
                return task
            time.sleep(0.01)
        raise TimeoutError("Official task integration timed out")

    try:
        service.submit([args.source], str(output))
        task_id = store.tasks()[0]["id"]
        task = wait_for(task_id, {"ready", "failed"}, 160)
        if args.expect_auth_required:
            passed = task["state"] == "failed" and task["error_code"] == "AUTH_REQUIRED"
        elif task["state"] == "ready":
            service.retry(task_id)
            task = wait_for(task_id, {"completed", "failed"}, 660)
            passed = task["state"] == "completed"
        else:
            passed = False
        report = {
            "passed": passed,
            "states": states,
            "state": task["state"],
            "error_code": task["error_code"],
            "used_app_cookie": False,
            "production_enabled": bool(args.production_runtime),
            "authenticated_selection": authenticated,
            "task_id": task_id,
        }
        if task["state"] == "completed":
            directory = Path(task["final_dir"])
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            report.update(
                final_directory=str(directory),
                files=len(manifest["files"]),
                committed_with_token=bool(manifest.get("commit_token")),
            )
        (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if passed else 1
    finally:
        service.shutdown()
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
