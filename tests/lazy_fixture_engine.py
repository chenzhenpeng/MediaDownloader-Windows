"""Load native parser dependencies only after the persistent stdin reader starts."""

import asyncio

from media_downloader.adapter import ParseHubAdapter
from media_downloader.worker import main


async def inspect_without_network(self):
    await asyncio.sleep(30)


ParseHubAdapter.inspect = inspect_without_network
raise SystemExit(main())
