#!/usr/bin/env python3
"""Run the headed crawl worker on the local host."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workers.run_headed_crawl_worker import main


if __name__ == "__main__":
    asyncio.run(main())
