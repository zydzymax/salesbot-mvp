"""
CRUD operations for database models
Async operations with proper error handling
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select, update, delete, and_, or_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError

from .models import (
    Call, Manager, AnalysisCache, Report, SystemLog, TokenStorage,
    TranscriptionStatus, AnalysisStatus, ReportType
)


async def retry_on_lock(func, *args, session=None, max_retries=5, initial_delay=0.1, **kwargs):
    """Retry function on database lock with exponential backoff"""
    from sqlalchemy.exc import PendingRollbackError

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except (OperationalError, PendingRollbackError) as e:
            error_str = str(e)
            if ("database is locked" in error_str or "PendingRollbackError" in error_str) and attempt < max_retries - 1:
                # Rollback the session before retry
                if session:
                    await session.rollback()
                delay = initial_delay * (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            raise


class CallCRUD:
    """CRUD operations for Call model"""
    
    @staticmethod
    async def create_call(
        session: AsyncSession,
        amocrm_call_id: str,
        manager_id: int,
        amocrm_lead_id: Optional[str] = None,
        client_phone: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        audio_url: Optional[str] = None
    ) -> Call:
        """Create a new call record"""
        call = Call(
            amocrm_call_id=amocrm_call_id,
            amocrm_lead_id=amocrm_lead_id,
            manager_id=manager_id,
            client_phone=client_phone,
            duration_seconds=duration_seconds,
            audio_url=audio_url
        )
        session.add(call)
        # Retry commit on database lock
        await retry_on_lock(session.commit, session=session)
        await session.refresh(call)
        return call
    
    @staticmethod
    async def get_call_by_id(session: AsyncSession, call_id: UUID) -> Optional[Call]:
        """Get call by UUID"""
        result = await session.execute(
            select(Call)
            .options(selectinload(Call.manager))
            .where(Call.id == call_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_call_by_amocrm_id(
        session: AsyncSession, 
        amocrm_call_id: str
    ) -> Optional[Call]:
        """Get call by AmoCRM call ID"""
        result = await session.execute(
            select(Call)
            .options(selectinload(Call.manager))
            .where(Call.amocrm_call_id == amocrm_call_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_calls_for_processing(
        session: AsyncSession,
        transcription_status: TranscriptionStatus = TranscriptionStatus.PENDING,
        limit: int = 10
    ) -> List[Call]:
        """Get calls that need processing"""
        result = await session.execute(
            select(Call)
            .options(selectinload(Call.manager))
            .where(Call.transcription_status == transcription_status)
            .order_by(Call.created_at)
            .limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def update_transcription(
        session: AsyncSession,
        call_id: UUID,
        status: TranscriptionStatus,
        text: Optional[str] = None,
        segments: Optional[List[Dict[str, Any]]] = None,
        error: Optional[str] = None
    ) -> bool:
        """Update call transcription status, text and segments"""
        values = {
            "transcription_status": status,
            "transcription_text": text,
            "transcription_error": error,
            "updated_at": datetime.utcnow()
        }

        # Add segments if provided
        if segments is not None:
            values["transcription_segments"] = segments

        result = await session.execute(
            update(Call)
            .where(Call.id == call_id)
            .values(**values)
        )
        await session.commit()
        return result.rowcount > 0
    
    @staticmethod
    async def update_analysis(
        session: AsyncSession,
        call_id: UUID,
        status: AnalysisStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """Update call analysis status and result"""
        result = await session.execute(
            update(Call)
            .where(Call.id == call_id)
            .values(
                analysis_status=status,
                analysis_result=result,
                analysis_error=error,
                updated_at=datetime.utcnow()
            )
        )
        await session.commit()
        return result.rowcount > 0
    
    @staticmethod
    async def get_manager_calls(
        session: AsyncSession,
        manager_id: int,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50
    ) -> List[Call]:
        """Get calls for specific manager"""
        query = select(Call).where(Call.manager_id == manager_id)
        
        if date_from:
            query = query.where(Call.created_at >= date_from)
        if date_to:
            query = query.where(Call.created_at <= date_to)
            
        query = query.order_by(desc(Call.created_at)).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()


class ManagerCRUD:
    """CRUD operations for Manager model"""
    
    @staticmethod
    async def create_manager(
        session: AsyncSession,
        amocrm_user_id: str,
        name: str,
        email: Optional[str] = None
    ) -> Manager:
        """Create a new manager"""
        manager = Manager(
            amocrm_user_id=amocrm_user_id,
            name=name,
            email=email
        )
        session.add(manager)
        # Retry commit on database lock
        await retry_on_lock(session.commit, session=session)
        await session.refresh(manager)
        return manager
    
    @staticmethod
    async def get_manager(
        session: AsyncSession,
        manager_id: int
    ) -> Optional[Manager]:
        """Get manager by ID"""
        result = await session.execute(
            select(Manager).where(Manager.id == manager_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_manager_by_amocrm_id(
        session: AsyncSession,
        amocrm_user_id: str
    ) -> Optional[Manager]:
        """Get manager by AmoCRM user ID"""
        result = await session.execute(
            select(Manager).where(Manager.amocrm_user_id == amocrm_user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_manager_by_telegram_id(
        session: AsyncSession,
        telegram_chat_id: str
    ) -> Optional[Manager]:
        """Get manager by Telegram chat ID"""
        result = await session.execute(
            select(Manager).where(Manager.telegram_chat_id == telegram_chat_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def link_telegram(
        session: AsyncSession,
        manager_id: int,
        telegram_chat_id: str
    ) -> bool:
        """Link manager with Telegram chat"""
        result = await session.execute(
            update(Manager)
            .where(Manager.id == manager_id)
            .values(
                telegram_chat_id=telegram_chat_id,
                updated_at=datetime.utcnow()
            )
        )
        await session.commit()
        return result.rowcount > 0
    
    @staticmethod
    async def get_active_managers(session: AsyncSession, monitored_only: bool = True) -> List[Manager]:
        """
        Get active managers

        Args:
            monitored_only: If True, returns only managers with is_monitored=True
        """
        query = select(Manager).where(Manager.is_active == True)

        if monitored_only:
            query = query.where(Manager.is_monitored == True)

        query = query.order_by(Manager.name)
        result = await session.execute(query)
        return result.scalars().all()


class AlertSettingsCRUD:
    """CRUD operations for AlertSettings model"""

    @staticmethod
    async def get_alert_settings(session: AsyncSession):
        """Get alert settings (singleton)"""
        from .models import AlertSettings
        result = await session.execute(
            select(AlertSettings).limit(1)
        )
        settings = result.scalar_one_or_none()

        # Create default if not exists
        if not settings:
            settings = AlertSettings(id=1)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)

        return settings

    @staticmethod
    async def update_alert_settings(
        session: AsyncSession,
        **kwargs
    ) -> bool:
        """Update alert settings"""
        from .models import AlertSettings

        # Get or create settings
        result = await session.execute(
            select(AlertSettings).limit(1)
        )
        settings = result.scalar_one_or_none()

        if not settings:
            settings = AlertSettings(id=1, **kwargs)
            session.add(settings)
        else:
            for key, value in kwargs.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)

        await session.commit()
        return True


class AnalysisCacheCRUD:
    """CRUD operations for AnalysisCache model"""
    
    @staticmethod
    async def get_cached_analysis(
        session: AsyncSession,
        text_hash: str,
        analysis_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached analysis result"""
        result = await session.execute(
            select(AnalysisCache)
            .where(
                and_(
                    AnalysisCache.text_hash == text_hash,
                    AnalysisCache.analysis_type == analysis_type,
                    AnalysisCache.expires_at > datetime.utcnow()
                )
            )
        )
        cache_entry = result.scalar_one_or_none()
        return cache_entry.result if cache_entry else None
    
    @staticmethod
    async def save_analysis_cache(
        session: AsyncSession,
        text_hash: str,
        analysis_type: str,
        result: Dict[str, Any],
        ttl_seconds: int = 86400
    ) -> None:
        """Save analysis result to cache"""
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        
        cache_entry = AnalysisCache(
            text_hash=text_hash,
            analysis_type=analysis_type,
            result=result,
            expires_at=expires_at
        )
        session.add(cache_entry)
        await session.commit()
    
    @staticmethod
    async def cleanup_expired_cache(session: AsyncSession) -> int:
        """Remove expired cache entries"""
        result = await session.execute(
            delete(AnalysisCache)
            .where(AnalysisCache.expires_at <= datetime.utcnow())
        )
        await session.commit()
        return result.rowcount


class ReportCRUD:
    """CRUD operations for Report model"""
    
    @staticmethod
    async def create_report(
        session: AsyncSession,
        report_type: ReportType,
        date_from: datetime,
        date_to: datetime,
        data: Dict[str, Any],
        manager_id: Optional[int] = None,
        file_path: Optional[str] = None
    ) -> Report:
        """Create a new report"""
        report = Report(
            report_type=report_type,
            manager_id=manager_id,
            date_from=date_from,
            date_to=date_to,
            data=data,
            file_path=file_path
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report
    
    @staticmethod
    async def get_recent_reports(
        session: AsyncSession,
        report_type: Optional[ReportType] = None,
        manager_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Report]:
        """Get recent reports"""
        query = select(Report)
        
        if report_type:
            query = query.where(Report.report_type == report_type)
        if manager_id:
            query = query.where(Report.manager_id == manager_id)
            
        query = query.order_by(desc(Report.created_at)).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()


class SystemLogCRUD:
    """CRUD operations for SystemLog model"""
    
    @staticmethod
    async def log_event(
        session: AsyncSession,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ) -> None:
        """Log system event"""
        log_entry = SystemLog(
            level=level,
            message=message,
            context=context,
            source=source
        )
        session.add(log_entry)
        await session.commit()
    
    @staticmethod
    async def get_recent_logs(
        session: AsyncSession,
        level: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100
    ) -> List[SystemLog]:
        """Get recent log entries"""
        query = select(SystemLog)
        
        if level:
            query = query.where(SystemLog.level == level)
        if source:
            query = query.where(SystemLog.source == source)
            
        query = query.order_by(desc(SystemLog.created_at)).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def cleanup_old_logs(
        session: AsyncSession,
        days_to_keep: int = 30
    ) -> int:
        """Remove old log entries"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        result = await session.execute(
            delete(SystemLog)
            .where(SystemLog.created_at < cutoff_date)
        )
        await session.commit()
        return result.rowcount


class TokenStorageCRUD:
    """CRUD operations for TokenStorage model"""
    
    @staticmethod
    async def save_token(
        session: AsyncSession,
        service: str,
        token_type: str,
        encrypted_token: str,
        expires_at: Optional[datetime] = None
    ) -> None:
        """Save encrypted token"""
        # Delete existing token if any
        await session.execute(
            delete(TokenStorage)
            .where(
                and_(
                    TokenStorage.service == service,
                    TokenStorage.token_type == token_type
                )
            )
        )
        
        token = TokenStorage(
            service=service,
            token_type=token_type,
            encrypted_token=encrypted_token,
            expires_at=expires_at
        )
        session.add(token)
        await session.commit()
    
    @staticmethod
    async def get_token(
        session: AsyncSession,
        service: str,
        token_type: str
    ) -> Optional[str]:
        """Get encrypted token"""
        result = await session.execute(
            select(TokenStorage)
            .where(
                and_(
                    TokenStorage.service == service,
                    TokenStorage.token_type == token_type
                )
            )
        )
        token = result.scalar_one_or_none()
        return token.encrypted_token if token else None