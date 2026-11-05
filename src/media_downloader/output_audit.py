"""Validate saved responses without deleting user files."""

from pathlib import Path

from .errors import AppError
from .media_validation import validate_media_payloads
from .storage import valid_output_directory


def audit_outputs(jobs):
    invalid = []
    for task, paths in jobs:
        directory = Path(task["final_dir"])
        try:
            if not valid_output_directory(task["output_root"], directory, task["id"], task["attempt_id"]):
                continue
            files = []
            for value in paths:
                relative = Path(value)
                path = directory / relative
                if relative.is_absolute() or ".." in relative.parts or ":" in value:
                    continue
                if not path.resolve().is_relative_to(directory) or any(
                    p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p != directory.parent
                ):
                    continue
                if path.is_file():
                    files.append(path)
            validate_media_payloads(files)
        except AppError:
            invalid.append((task["id"], task["attempt_id"], task["revision"]))
        except OSError:
            # Missing, moved or temporarily locked files are not evidence of corruption.
            continue
    return invalid
