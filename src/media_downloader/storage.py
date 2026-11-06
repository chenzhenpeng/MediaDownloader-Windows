from __future__ import annotations

import os
import re
from pathlib import Path

from .contracts import platform_for_url
from .media_paths import (
    PLATFORM_FOLDERS as PLATFORM_FOLDERS,
)
from .media_paths import (
    download_stem as download_stem,
)
from .media_paths import (
    output_directory as output_directory,
)
from .media_paths import (
    safe_name as safe_name,
)
from .media_paths import (
    valid_output_directory as valid_output_directory,
)


def data_directory() -> Path:
    override = os.environ.get("MEDIA_DOWNLOADER_DATA_DIR")
    base = (
        Path(override)
        if override
        else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MediaDownloader" / "v6"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base






def extract_links(text: str) -> list[str]:
    links = []
    for match in re.finditer(r"https?://[^\s<>\"\u3000]+", text, flags=re.I):
        url = match.group().rstrip(".,;!?，。；！？）】》)")
        if platform_for_url(url) is None:
            continue
        if url not in links:
            links.append(url)
    return links


from .repository import Store as Store  # noqa: E402
