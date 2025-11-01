#!/usr/bin/env python3
"""
Process pending calls - add them to task queue for transcription
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database.init_db import db_manager
from app.database.crud import CallCRUD
from app.database.models import TranscriptionStatus
from app.tasks.queue import task_queue
from app.tasks.workers import TranscribeCallTask
import structlog

logger = structlog.get_logger()


async def process_pending_calls():
    """Process all pending calls with audio"""

    # Initialize database
    await db_manager.init_database()

    # Start task queue
    await task_queue.start()

    try:
        async with db_manager.get_session() as session:
            # Get pending calls with audio - use direct query to filter by audio_url
            from sqlalchemy import select, and_
            from app.database.models import Call

            stmt = select(Call).where(
                and_(
                    Call.transcription_status == TranscriptionStatus.PENDING,
                    Call.audio_url.isnot(None),
                    Call.audio_url != '',
                    Call.duration_seconds > 5
                )
            ).limit(100)

            result = await session.execute(stmt)
            calls = result.scalars().all()

            logger.info(f"Found {len(calls)} pending calls to process")

            added_count = 0
            skipped_no_audio = 0
            skipped_short = 0

            for call in calls:
                # Debug logging
                logger.info(f"Checking call",
                           call_id=str(call.id),
                           has_audio=bool(call.audio_url),
                           duration=call.duration_seconds)

                if not call.audio_url:
                    skipped_no_audio += 1
                    continue

                if not call.duration_seconds or call.duration_seconds <= 5:
                    skipped_short += 1
                    continue

                # Create transcription task
                task = TranscribeCallTask(
                    call_id=str(call.id),
                    recording_url=call.audio_url
                )

                # Add to queue
                task_id = await task_queue.add_task(task.execute, priority=5)
                logger.info(f"Added call {call.id} to queue", task_id=task_id)
                added_count += 1

            logger.info(f"Processing summary",
                       added=added_count,
                       skipped_no_audio=skipped_no_audio,
                       skipped_short=skipped_short,
                       total_checked=len(calls))

        # Wait for queue to process tasks
        logger.info("Waiting for tasks to complete...")

        # Wait up to 30 minutes
        for i in range(180):
            stats = task_queue.get_stats()
            logger.info(f"Queue stats", **stats)

            if stats['queue_size'] == 0 and stats['active_tasks'] == 0:
                logger.info("All tasks completed!")
                break

            await asyncio.sleep(10)

    finally:
        # Stop queue
        await task_queue.stop()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(process_pending_calls())
