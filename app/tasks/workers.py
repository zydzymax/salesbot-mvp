"""
Specific task workers for different operations
Transcription, analysis, reporting, notifications
"""

import os
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

import structlog

from ..config import get_settings
from ..database.init_db import db_manager
from ..database.crud import CallCRUD
from ..database.models import TranscriptionStatus, AnalysisStatus
from ..audio.processor import AudioProcessor
from ..audio.transcriber import WhisperTranscriber
from ..analysis.analyzer import CallAnalyzer
from ..amocrm.client import amocrm_client
from ..utils.helpers import ensure_directory_exists, format_duration

logger = structlog.get_logger("salesbot.tasks.workers")


class TranscribeCallTask:
    """Task to transcribe call recording"""
    
    def __init__(self, call_id: str, recording_url: str):
        self.call_id = call_id
        self.recording_url = recording_url
        self.audio_processor = AudioProcessor()
        self.transcriber = WhisperTranscriber()
        self.settings = get_settings()
    
    async def execute(self) -> Dict[str, Any]:
        """Execute transcription task"""
        logger.info(f"Starting transcription", call_id=self.call_id)
        
        try:
            # Update status to processing
            async with db_manager.get_session() as session:
                await CallCRUD.update_transcription(
                    session,
                    UUID(self.call_id),
                    TranscriptionStatus.PROCESSING
                )
            
            # Download audio file
            audio_data = await amocrm_client.download_call_recording(self.recording_url)
            if not audio_data:
                raise Exception("Failed to download recording")
            
            logger.info(f"Downloaded recording", call_id=self.call_id, size_bytes=len(audio_data))
            
            # Process audio
            processed_audio = await self.audio_processor.process_for_transcription(audio_data)
            if not processed_audio:
                raise Exception("Failed to process audio")
            
            # Validate duration
            duration = self.audio_processor.get_audio_duration(processed_audio)
            if duration > self.settings.max_audio_duration_seconds:
                raise Exception(f"Audio too long: {duration}s > {self.settings.max_audio_duration_seconds}s")
            
            logger.info(f"Audio processed", call_id=self.call_id, duration=format_duration(duration))
            
            # Transcribe
            transcription = await self.transcriber.transcribe(processed_audio)
            if not transcription or len(transcription.strip()) < 10:
                raise Exception("Transcription too short or empty")
            
            logger.info(f"Transcription completed", call_id=self.call_id, length=len(transcription))
            
            # Update database
            async with db_manager.get_session() as session:
                success = await CallCRUD.update_transcription(
                    session,
                    UUID(self.call_id),
                    TranscriptionStatus.COMPLETED,
                    text=transcription
                )
                
                if not success:
                    raise Exception("Failed to save transcription")
            
            # Queue analysis task
            from .queue import task_queue
            analysis_task = AnalyzeCallTask(self.call_id)
            await task_queue.add_task(analysis_task.execute, priority=3)
            
            return {
                "status": "completed",
                "transcription_length": len(transcription),
                "audio_duration": duration
            }
            
        except Exception as e:
            logger.error(f"Transcription failed", call_id=self.call_id, error=str(e))
            
            # Update status to failed
            async with db_manager.get_session() as session:
                await CallCRUD.update_transcription(
                    session,
                    UUID(self.call_id),
                    TranscriptionStatus.FAILED,
                    error=str(e)
                )
            
            raise


class AnalyzeCallTask:
    """Task to analyze transcribed call"""
    
    def __init__(self, call_id: str):
        self.call_id = call_id
        self.analyzer = CallAnalyzer()
    
    async def execute(self) -> Dict[str, Any]:
        """Execute analysis task"""
        logger.info(f"Starting analysis", call_id=self.call_id)
        
        try:
            # Get call with transcription
            async with db_manager.get_session() as session:
                call = await CallCRUD.get_call_by_id(session, UUID(self.call_id))
                if not call:
                    raise Exception("Call not found")
                
                if not call.transcription_text:
                    raise Exception("No transcription available")
                
                # Update status to processing
                await CallCRUD.update_analysis(
                    session,
                    UUID(self.call_id),
                    AnalysisStatus.PROCESSING
                )
            
            # Perform analysis
            analysis_result = await self.analyzer.analyze_call(
                transcription=call.transcription_text,
                call_type="general"  # Could be determined based on call data
            )
            
            logger.info(f"Analysis completed", call_id=self.call_id)
            
            # Update database
            async with db_manager.get_session() as session:
                success = await CallCRUD.update_analysis(
                    session,
                    UUID(self.call_id),
                    AnalysisStatus.COMPLETED,
                    result=analysis_result.dict() if hasattr(analysis_result, 'dict') else analysis_result
                )
                
                if not success:
                    raise Exception("Failed to save analysis")
            
            # Queue notification task if needed
            if analysis_result.get("follow_up_required"):
                notification_task = SendNotificationTask(
                    call_id=self.call_id,
                    notification_type="follow_up_required"
                )
                from .queue import task_queue
                await task_queue.add_task(notification_task.execute, priority=7)
            
            return {
                "status": "completed",
                "overall_score": analysis_result.get("overall_score", 0),
                "follow_up_required": analysis_result.get("follow_up_required", False)
            }
            
        except Exception as e:
            logger.error(f"Analysis failed", call_id=self.call_id, error=str(e))
            
            # Update status to failed
            async with db_manager.get_session() as session:
                await CallCRUD.update_analysis(
                    session,
                    UUID(self.call_id),
                    AnalysisStatus.FAILED,
                    error=str(e)
                )
            
            raise


class GenerateReportTask:
    """Task to generate reports"""
    
    def __init__(
        self,
        report_type: str,
        manager_id: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ):
        self.report_type = report_type
        self.manager_id = manager_id
        self.date_from = date_from or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        self.date_to = date_to or datetime.utcnow()
    
    async def execute(self) -> Dict[str, Any]:
        """Execute report generation"""
        logger.info(
            f"Generating report",
            report_type=self.report_type,
            manager_id=self.manager_id
        )
        
        try:
            from ..reports.generator import ReportGenerator
            
            generator = ReportGenerator()
            
            # Generate report based on type
            if self.report_type == "daily":
                report_data = await generator.generate_daily_report(
                    manager_id=self.manager_id,
                    date=self.date_from.date()
                )
            elif self.report_type == "weekly":
                report_data = await generator.generate_weekly_report(
                    manager_id=self.manager_id,
                    week_start=self.date_from
                )
            else:
                raise Exception(f"Unknown report type: {self.report_type}")
            
            # Save report to database
            async with db_manager.get_session() as session:
                from ..database.crud import ReportCRUD
                from ..database.models import ReportType
                
                report = await ReportCRUD.create_report(
                    session=session,
                    report_type=ReportType(self.report_type),
                    date_from=self.date_from,
                    date_to=self.date_to,
                    data=report_data,
                    manager_id=self.manager_id
                )
            
            logger.info(f"Report generated", report_id=report.id)
            
            return {
                "status": "completed",
                "report_id": report.id,
                "data": report_data
            }
            
        except Exception as e:
            logger.error(f"Report generation failed", error=str(e))
            raise


class SendNotificationTask:
    """Task to send notifications via Telegram"""
    
    def __init__(self, call_id: str, notification_type: str, data: Optional[Dict] = None):
        self.call_id = call_id
        self.notification_type = notification_type
        self.data = data or {}
    
    async def execute(self) -> Dict[str, Any]:
        """Execute notification sending"""
        logger.info(
            f"Sending notification",
            call_id=self.call_id,
            type=self.notification_type
        )
        
        try:
            # Get call and manager info
            async with db_manager.get_session() as session:
                call = await CallCRUD.get_call_by_id(session, UUID(self.call_id))
                if not call or not call.manager:
                    raise Exception("Call or manager not found")
                
                if not call.manager.telegram_chat_id:
                    logger.info(f"Manager has no Telegram, skipping notification")
                    return {"status": "skipped", "reason": "no_telegram"}
            
            # Send notification via Telegram bot
            from ..bot.telegram_bot import send_notification
            
            message = self._format_notification_message(call, self.notification_type)
            
            success = await send_notification(
                chat_id=call.manager.telegram_chat_id,
                message=message
            )
            
            if success:
                logger.info(f"Notification sent", call_id=self.call_id)
                return {"status": "sent"}
            else:
                raise Exception("Failed to send Telegram notification")
            
        except Exception as e:
            logger.error(f"Notification sending failed", call_id=self.call_id, error=str(e))
            raise
    
    def _format_notification_message(self, call, notification_type: str) -> str:
        """Format notification message"""
        if notification_type == "follow_up_required":
            return (
                f"🔔 Требуется дополнительная работа по звонку\n\n"
                f"📞 Звонок: {call.amocrm_call_id}\n"
                f"📱 Телефон: {call.client_phone or 'не указан'}\n"
                f"⏱ Длительность: {format_duration(call.duration_seconds or 0)}\n"
                f"📊 Результат анализа показал необходимость follow-up\n\n"
                f"Используйте /analyze {call.amocrm_call_id} для подробностей"
            )
        elif notification_type == "analysis_completed":
            analysis = call.analysis_result or {}
            score = analysis.get("overall_score", 0)
            
            return (
                f"✅ Анализ звонка завершен\n\n"
                f"📞 Звонок: {call.amocrm_call_id}\n"
                f"📊 Оценка: {score}/100\n"
                f"📱 Телефон: {call.client_phone or 'не указан'}\n\n"
                f"Используйте /analyze {call.amocrm_call_id} для подробностей"
            )
        else:
            return f"Уведомление по звонку {call.amocrm_call_id}"


class CleanupTask:
    """Task to cleanup old data"""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def execute(self) -> Dict[str, Any]:
        """Execute cleanup"""
        logger.info("Starting cleanup task")
        
        try:
            # Cleanup database
            async with db_manager.get_session() as session:
                from ..database.crud import AnalysisCacheCRUD, SystemLogCRUD
                
                # Clean expired cache
                cache_count = await AnalysisCacheCRUD.cleanup_expired_cache(session)
                
                # Clean old logs
                log_count = await SystemLogCRUD.cleanup_old_logs(session, days_to_keep=30)
            
            # Cleanup audio files
            audio_count = self._cleanup_audio_files()
            
            # Cleanup task queue
            from .queue import task_queue
            await task_queue.cleanup_old_tasks(hours=24)
            
            result = {
                "status": "completed",
                "cleaned_cache_entries": cache_count,
                "cleaned_log_entries": log_count,
                "cleaned_audio_files": audio_count
            }
            
            logger.info("Cleanup completed", **result)
            return result
            
        except Exception as e:
            logger.error(f"Cleanup failed", error=str(e))
            raise
    
    def _cleanup_audio_files(self) -> int:
        """Cleanup old audio files"""
        audio_path = self.settings.audio_storage_path
        if not os.path.exists(audio_path):
            return 0
        
        count = 0
        cutoff_time = datetime.utcnow().timestamp() - (7 * 24 * 3600)  # 7 days
        
        try:
            for filename in os.listdir(audio_path):
                file_path = os.path.join(audio_path, filename)
                if os.path.isfile(file_path):
                    if os.path.getmtime(file_path) < cutoff_time:
                        os.remove(file_path)
                        count += 1
        except Exception as e:
            logger.error(f"Error cleaning audio files: {e}")
        
        return count