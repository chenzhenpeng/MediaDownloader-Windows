"""Explicit candidate layouts: development venv or self-contained Python embed."""

from pathlib import Path


def candidate_python(directory: Path) -> Path:
    if (directory / "profile.json").is_file():
        from .execution_profile import load_bundle

        return Path(load_bundle(directory).program)
    candidates = [directory / "python.exe", directory / "Scripts/python.exe"]
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise ValueError("Missing or ambiguous candidate Python layout")
    return found[0]
