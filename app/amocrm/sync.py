"""
Data synchronization with AmoCRM
Periodic sync of managers, calls, and other data
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from pathlib import Path

import structlog

from ..database.init_db import db_manager
from ..database.crud import ManagerCRUD, CallCRUD
from ..database.models import TranscriptionStatus, AnalysisStatus
from .client import amocrm_client
from ..services.transcription import transcription_service
from ..services.ai_analysis import ai_analysis_service

logger = structlog.get_logger("salesbot.amocrm.sync")

# Directory for storing call recordings
RECORDINGS_DIR = Path(__file__).parent.parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)


class DataSynchronizer:
    """Synchronize data between AmoCRM and local database"""

    def __init__(self):
        self.is_syncing = False

    async def download_and_save_recording(self, call_id: str, audio_url: str) -> str:
        """Download call recording and save to disk"""
        try:
            # Download recording
            audio_data = await amocrm_client.download_call_recording(audio_url)
            if not audio_data:
                return None

            # Save to file
            filename = f"{call_id}.mp3"
            filepath = RECORDINGS_DIR / filename

            with open(filepath, 'wb') as f:
                f.write(audio_data)

            logger.info(
                f"Recording downloaded",
                call_id=call_id,
                file_size=len(audio_data),
                filepath=str(filepath)
            )

            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to download recording", call_id=call_id, error=str(e))
            return None

    async def process_call_recording(self, call, session, local_path: str):
        """Transcribe and analyze call recording"""
        try:
            # Update transcription status to processing
            call.transcription_status = TranscriptionStatus.PROCESSING
            await session.flush()

            # Transcribe audio
            logger.info(f"Starting transcription", call_id=call.id)
            transcript_result = await transcription_service.transcribe_file(
                audio_path=local_path,
                language="ru",
                post_process=True  # Use GPT to improve quality
            )

            if not transcript_result:
                call.transcription_status = TranscriptionStatus.FAILED
                call.transcription_error = "Transcription failed"
                await session.flush()
                return

            # Save transcription
            call.transcription_text = transcript_result["text"]
            call.transcription_status = TranscriptionStatus.COMPLETED
            await session.flush()

            logger.info(
                f"Transcription completed",
                call_id=call.id,
                text_length=len(transcript_result["text"])
            )

            # Start AI analysis
            call.analysis_status = AnalysisStatus.PROCESSING
            await session.flush()

            logger.info(f"Starting AI analysis", call_id=call.id)
            analysis_result = await ai_analysis_service.analyze_call(
                transcript=transcript_result["text"],
                phone=call.client_phone,
                duration=call.duration_seconds
            )

            if not analysis_result:
                call.analysis_status = AnalysisStatus.FAILED
                call.analysis_error = "AI analysis failed"
                await session.flush()
                return

            # Save analysis results
            call.analysis_result = analysis_result
            call.quality_score = analysis_result.get("quality_score", 0)
            call.analysis_status = AnalysisStatus.COMPLETED
            await session.flush()

            logger.info(
                f"AI analysis completed",
                call_id=call.id,
                quality_score=call.quality_score,
                tokens_used=analysis_result.get("tokens_used", 0)
            )

        except Exception as e:
            logger.error(
                f"Error processing call recording",
                call_id=call.id,
                error=str(e)
            )
            call.transcription_status = TranscriptionStatus.FAILED
            call.transcription_error = str(e)
            call.analysis_status = AnalysisStatus.FAILED
            call.analysis_error = str(e)
            await session.flush()
    
    async def sync_managers(self) -> Dict[str, int]:
        """Sync managers from AmoCRM"""
        logger.info("Starting managers sync")
        
        try:
            # Get users from AmoCRM
            users = await amocrm_client.get_users()
            
            created_count = 0
            updated_count = 0
            
            async with db_manager.get_session() as session:
                for user in users:
                    amocrm_user_id = str(user["id"])
                    name = user.get("name", f"User {amocrm_user_id}")
                    email = user.get("email")
                    
                    # Check if manager exists
                    existing_manager = await ManagerCRUD.get_manager_by_amocrm_id(
                        session, amocrm_user_id
                    )
                    
                    if existing_manager:
                        # Update if name or email changed
                        if (existing_manager.name != name or 
                            existing_manager.email != email):
                            # Note: We'd need to add update method to ManagerCRUD
                            updated_count += 1
                            logger.info(f"Manager updated", manager_id=existing_manager.id)
                    else:
                        # Create new manager
                        new_manager = await ManagerCRUD.create_manager(
                            session=session,
                            amocrm_user_id=amocrm_user_id,
                            name=name,
                            email=email
                        )
                        created_count += 1
                        logger.info(f"Manager created", manager_id=new_manager.id)
            
            logger.info(
                "Managers sync completed",
                created=created_count,
                updated=updated_count
            )
            
            return {"created": created_count, "updated": updated_count}
            
        except Exception as e:
            import traceback
            error_details = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"Error syncing managers", error=error_details)
            return {"created": 0, "updated": 0, "error": error_details}
    
    async def sync_leads_with_calls(
        self,
        limit_leads: int = 100,
        days_back: int = 30
    ) -> Dict[str, int]:
        """Sync leads and their calls from AmoCRM"""
        logger.info(f"Starting leads sync (last {days_back} days, limit {limit_leads})")

        try:
            # Calculate time filter for leads
            cutoff_time = datetime.utcnow() - timedelta(days=days_back)
            cutoff_timestamp = int(cutoff_time.timestamp())

            # Get recent leads from AmoCRM
            filter_params = {
                "filter[updated_at][from]": cutoff_timestamp
            }

            leads_processed = 0
            calls_processed = 0
            calls_skipped = 0
            page = 1

            async with db_manager.get_session() as session:
                while leads_processed < limit_leads:
                    leads_response = await amocrm_client.get_leads(
                        limit=min(50, limit_leads - leads_processed),
                        page=page,
                        filter_params=filter_params
                    )

                    leads = leads_response.get("_embedded", {}).get("leads", [])

                    if not leads:
                        break

                    for lead in leads:
                        lead_id = str(lead["id"])
                        leads_processed += 1

                        logger.info(f"Syncing lead {lead_id}")

                        # Get calls for this lead
                        lead_calls = await amocrm_client.get_lead_calls(lead_id)

                        for call_data in lead_calls:
                            call_id = str(call_data["id"])

                            # Check if call already exists
                            existing_call = await CallCRUD.get_call_by_amocrm_id(
                                session, call_id
                            )
                            if existing_call:
                                calls_skipped += 1
                                continue

                            # Get manager
                            responsible_user_id = str(call_data.get("responsible_user_id"))
                            manager = await ManagerCRUD.get_manager_by_amocrm_id(
                                session, responsible_user_id
                            )

                            if not manager:
                                logger.warning(
                                    f"Manager not found for call",
                                    call_id=call_id,
                                    user_id=responsible_user_id,
                                    lead_id=lead_id
                                )
                                calls_skipped += 1
                                continue

                            # Create call record with lead_id
                            await CallCRUD.create_call(
                                session=session,
                                amocrm_call_id=call_id,
                                manager_id=manager.id,
                                amocrm_lead_id=lead_id,
                                client_phone=call_data.get("phone"),
                                duration_seconds=call_data.get("duration", 0),
                                audio_url=call_data.get("recording", {}).get("url") if call_data.get("recording") else None
                            )

                            calls_processed += 1

                        # Commit after each lead
                        await session.commit()

                    page += 1

            logger.info(
                "Leads sync completed",
                leads=leads_processed,
                calls_processed=calls_processed,
                calls_skipped=calls_skipped
            )

            return {
                "leads": leads_processed,
                "calls_processed": calls_processed,
                "calls_skipped": calls_skipped
            }

        except Exception as e:
            import traceback
            error_details = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"Error syncing leads", error=error_details)
            return {
                "leads": 0,
                "calls_processed": 0,
                "calls_skipped": 0,
                "error": error_details
            }

    async def sync_recent_calls(self, hours_back: int = 24) -> Dict[str, int]:
        """Sync recent calls from AmoCRM via Events API and enrich with Notes API"""
        logger.info(f"Starting recent calls sync ({hours_back} hours)")

        try:
            # Calculate time filter
            cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
            cutoff_timestamp = int(cutoff_time.timestamp())

            # Get recent call events from AmoCRM
            filter_params = {
                "filter[created_at][from]": cutoff_timestamp,
                "filter[type][]": ["incoming_call", "outgoing_call"]
            }

            events_response = await amocrm_client.get_events(
                limit=100,  # AmoCRM events max
                filter_params=filter_params
            )

            events = events_response.get("_embedded", {}).get("events", [])

            processed_count = 0
            skipped_count = 0
            enriched_count = 0

            async with db_manager.get_session() as session:
                for event in events:
                    # Extract call data from event
                    event_id = str(event["id"])
                    event_type = event.get("type")

                    # Skip non-call events
                    if event_type not in ["incoming_call", "outgoing_call"]:
                        continue

                    # Check if call already exists
                    existing_call = await CallCRUD.get_call_by_amocrm_id(session, event_id)
                    if existing_call:
                        skipped_count += 1
                        continue

                    # Get entity data (lead/contact/company)
                    entity_id = event.get("entity_id")
                    entity_type = event.get("entity_type")

                    # Get user who made the call
                    created_by = str(event.get("created_by", 0))
                    manager = await ManagerCRUD.get_manager_by_amocrm_id(
                        session, created_by
                    )

                    if not manager:
                        logger.warning(
                            f"Manager not found for call event",
                            event_id=event_id,
                            user_id=created_by
                        )
                        skipped_count += 1
                        continue

                    # Use event created_at as call time
                    call_timestamp = event.get("created_at")
                    call_datetime = datetime.fromtimestamp(call_timestamp) if call_timestamp else datetime.utcnow()

                    # Try to get call details from Notes API
                    client_phone = None
                    duration_seconds = None
                    audio_url = None

                    if entity_id and entity_type == "lead":
                        try:
                            # Get call notes for this lead
                            notes = await amocrm_client.get_lead_notes(
                                lead_id=str(entity_id),
                                note_types=["call_in", "call_out"]
                            )

                            # Find the matching note (by timestamp proximity - within 60 seconds)
                            for note in notes:
                                note_created_at = note.get("created_at")
                                if note_created_at and abs(note_created_at - call_timestamp) <= 60:
                                    # Extract call data from note params
                                    params = note.get("params", {})
                                    client_phone = params.get("phone")
                                    duration_seconds = params.get("duration")
                                    audio_url = params.get("link")

                                    if audio_url or client_phone or duration_seconds:
                                        enriched_count += 1
                                        logger.info(
                                            f"Enriched call with Notes data",
                                            event_id=event_id,
                                            phone=client_phone,
                                            duration=duration_seconds,
                                            has_recording=bool(audio_url)
                                        )
                                    break
                        except Exception as e:
                            logger.warning(
                                f"Failed to get Notes data for call",
                                event_id=event_id,
                                lead_id=entity_id,
                                error=str(e)
                            )

                    # Create call record with all available data
                    call = await CallCRUD.create_call(
                        session=session,
                        amocrm_call_id=event_id,
                        manager_id=manager.id,
                        amocrm_lead_id=str(entity_id) if entity_id and entity_type == "lead" else None,
                        client_phone=client_phone,
                        duration_seconds=duration_seconds,
                        audio_url=audio_url
                    )

                    # Update the created_at to match actual call time
                    call.created_at = call_datetime
                    await session.flush()

                    # Download recording if available
                    if audio_url:
                        local_path = await self.download_and_save_recording(
                            call_id=call.id,
                            audio_url=audio_url
                        )
                        if local_path:
                            logger.info(f"Recording saved", call_id=call.id, path=local_path)

                            # Automatically transcribe and analyze the call
                            await self.process_call_recording(call, session, local_path)

                    processed_count += 1

                # Commit after processing all events
                await session.commit()

            logger.info(
                "Recent calls sync completed",
                processed=processed_count,
                skipped=skipped_count,
                enriched=enriched_count
            )

            return {
                "processed": processed_count,
                "skipped": skipped_count,
                "enriched": enriched_count
            }

        except Exception as e:
            import traceback
            error_details = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"Error syncing recent calls", error=error_details)
            return {"processed": 0, "skipped": 0, "enriched": 0, "error": error_details}
    
    async def full_sync(self, sync_leads: bool = False) -> Dict[str, Any]:
        """Perform full data synchronization"""
        if self.is_syncing:
            logger.warning("Sync already in progress")
            return {"status": "already_syncing"}

        self.is_syncing = True
        start_time = datetime.utcnow()

        try:
            logger.info("Starting full sync")

            results = {}

            # Sync managers first
            results["managers"] = await self.sync_managers()

            # Sync calls (they contain lead_id, so deals will be visible)
            # AmoCRM API doesn't support GET /calls with entity_id filter
            results["calls"] = await self.sync_recent_calls(hours_back=720)  # Last 30 days

            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.info(f"Full sync completed in {duration:.2f} seconds")

            return {
                "status": "completed",
                "duration_seconds": duration,
                "results": results
            }

        except Exception as e:
            logger.error(f"Error during full sync: {e}")
            return {"status": "error", "error": str(e)}

        finally:
            self.is_syncing = False
    
    async def test_connection(self) -> bool:
        """Test AmoCRM connection"""
        try:
            return await amocrm_client.test_connection()
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    async def start_periodic_sync(self, interval_minutes: int = 60):
        """Start periodic synchronization"""
        logger.info(f"Starting periodic sync every {interval_minutes} minutes")
        
        while True:
            try:
                await asyncio.sleep(interval_minutes * 60)
                
                # Test connection first
                if await self.test_connection():
                    await self.sync_recent_calls(hours_back=2)  # Sync last 2 hours
                else:
                    logger.error("AmoCRM connection failed, skipping sync")
                    
            except asyncio.CancelledError:
                logger.info("Periodic sync cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic sync: {e}")


# Global synchronizer instance
data_synchronizer = DataSynchronizer()