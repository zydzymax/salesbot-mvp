"""
Re-transcribe a single call with new diarization feature
"""
import asyncio
import sys
from uuid import UUID

from app.database.init_db import db_manager
from app.database.crud import CallCRUD
from app.database.models import TranscriptionStatus
from app.tasks.workers import TranscribeCallTask
from app.tasks.queue import task_queue


async def main():
    call_id = "ebb69a979e704ba4804d8b0c0ba54de5"

    print(f"Re-transcribing call {call_id} with diarization...")

    # Initialize
    await db_manager.init_database()
    await task_queue.start()

    # Get call info
    async with db_manager.get_session() as session:
        call = await CallCRUD.get_call_by_id(session, UUID(call_id))
        if not call:
            print("Call not found!")
            return

        print(f"Call: {call.amocrm_call_id}")
        print(f"Audio URL: {call.audio_url[:50]}...")
        print(f"Current status: {call.transcription_status}")

        # Reset status to pending
        await CallCRUD.update_transcription(
            session,
            UUID(call_id),
            TranscriptionStatus.PENDING,
            text=None,
            segments=None,
            error=None
        )
        print("Reset to PENDING")

    # Create transcription task
    task = TranscribeCallTask(
        call_id=call_id,
        recording_url=call.audio_url
    )

    # Execute
    print("\nStarting transcription with diarization...")
    try:
        result = await task.execute()
        print(f"\n✅ Success!")
        print(f"Result: {result}")

        # Check segments
        async with db_manager.get_session() as session:
            call = await CallCRUD.get_call_by_id(session, UUID(call_id))
            if call.transcription_segments:
                print(f"\n📊 Segments: {len(call.transcription_segments)}")
                for i, seg in enumerate(call.transcription_segments[:3]):
                    speaker = "🎧 Менеджер" if seg['speaker'] == 'manager' else "💬 Клиент"
                    print(f"\n{speaker}:")
                    print(f"  {seg['text'][:100]}...")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    # Cleanup
    await task_queue.stop()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
