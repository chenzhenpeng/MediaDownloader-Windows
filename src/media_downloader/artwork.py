"""Optional bounded thumbnail fetching and normalization, exclusively in the engine."""

from __future__ import annotations

import asyncio
import base64
import io
import warnings
from collections.abc import Sequence

import httpx


def normalize_image(data: bytes) -> str | None:
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 20_000_000:
                    return None
                image.thumbnail((480, 320))
                output = io.BytesIO()
                image.convert("RGB").save(output, format="JPEG", quality=75)
        encoded = output.getvalue()
        return base64.b64encode(encoded).decode("ascii") if len(encoded) <= 120_000 else None
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


async def fetch_artwork(result, *, proxy=None, guard) -> list[str]:
    media = list(result.media) if isinstance(result.media, Sequence) else [result.media]
    urls = []
    for item in media[:3]:
        url = getattr(item, "thumb_url", None)
        if not url and type(item).__name__ in {"ImageRef", "LivePhotoRef"}:
            url = item.url
        if url and url not in urls:
            urls.append(url)
    if not urls:
        return []

    async def fetch():
        images = []
        async with httpx.AsyncClient(
            proxy=proxy,
            timeout=3,
            follow_redirects=True,
            max_redirects=4,
            event_hooks={"request": [guard]},
            headers={"Accept-Encoding": "identity", "Accept": "image/jpeg,image/png,image/webp"},
        ) as client:
            for url in urls:
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        if not response.headers.get("content-type", "").startswith("image/"):
                            continue
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            continue
                        data = bytearray()
                        async for chunk in response.aiter_raw(chunk_size=65536):
                            data.extend(chunk)
                            if len(data) > 2_000_000:
                                break
                        else:
                            normalized = await asyncio.to_thread(normalize_image, bytes(data))
                            if normalized:
                                images.append(normalized)
                except Exception:
                    # Artwork is optional; do not leak signed CDN URLs or break parsing.
                    continue
        return images

    try:
        return await asyncio.wait_for(fetch(), 5)
    except TimeoutError:
        return []
