"""
Progress API Routes - SSE endpoint for real-time scraping progress.
"""
import asyncio
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services.progress_store import get_progress_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scrape", tags=["progress"])


@router.get("/progress/stream")
async def stream_progress():
    """
    SSE endpoint for real-time scraping progress.
    Streams progress updates every second while scraping is active.
    Automatically closes when no active scrapes for 30 seconds.
    """
    async def event_generator():
        progress_store = get_progress_store()
        idle_count = 0
        max_idle = 30  # Close after 30 seconds of no activity

        while True:
            # Get current progress
            all_progress = progress_store.get_all()
            active_progress = progress_store.get_active()

            # Build event data
            event_data = {
                "active": active_progress,
                "all": all_progress,
                "has_active": len(active_progress) > 0
            }

            # Send SSE event
            yield f"data: {json.dumps(event_data)}\n\n"

            # Track idle time
            if len(active_progress) == 0:
                idle_count += 1
                if idle_count >= max_idle:
                    # Send close event and exit
                    yield f"data: {json.dumps({'closed': True, 'reason': 'idle'})}\n\n"
                    break
            else:
                idle_count = 0

            # Clean up old completed entries
            progress_store.clear_completed(max_age_seconds=60)

            await asyncio.sleep(1)  # Update every second

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.get("/progress")
async def get_progress():
    """
    Get current scraping progress (non-streaming).
    Useful for initial state or polling fallback.
    """
    progress_store = get_progress_store()
    all_progress = progress_store.get_all()
    active_progress = progress_store.get_active()

    return {
        "active": active_progress,
        "all": all_progress,
        "has_active": len(active_progress) > 0
    }
