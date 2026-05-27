#!/usr/bin/env python3
"""Run the dedicated manual-action helper on the local host."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workers.run_manual_action_helper import main


if __name__ == "__main__":
    asyncio.run(main())
