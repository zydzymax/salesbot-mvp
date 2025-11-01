"""
SQLAlchemy models for SalesBot MVP
Optimized for SQLite with proper indexing
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4, UUID
from enum import Enum

from sqlalchemy import (
    Column, String, Integer, DateTime, Boolean, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.sqlite import DATETIME
from sqlalchemy.types import TypeDecorator, CHAR


class GUID(TypeDecorator):
    """Platform-independent GUID type"""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif isinstance(value, UUID):
            return value.hex
        else:
            return str(value).replace('-', '')

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if len(value) == 32:
                return UUID(value)
            else:
                return UUID(value)


class TranscriptionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


Base = declarative_base()


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps"""
    created_at = Column(
        DATETIME, 
        default=datetime.utcnow, 
        nullable=False,
        index=True
    )
    updated_at = Column(
        DATETIME, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False
    )


class Call(Base, TimestampMixin):
    """Call records from AmoCRM"""
    __tablename__ = "calls"

    id = Column(GUID(), primary_key=True, default=uuid4)
    amocrm_call_id = Column(String(50), unique=True, nullable=False, index=True)
    amocrm_lead_id = Column(String(50), nullable=True, index=True)
    manager_id = Column(Integer, ForeignKey("managers.id"), nullable=False, index=True)
    client_phone = Column(String(20), nullable=True, index=True)
    duration_seconds = Column(Integer, nullable=True)
    audio_url = Column(Text, nullable=True)

    # Transcription fields
    transcription_status = Column(
        String(20),
        default=TranscriptionStatus.PENDING,
        nullable=False,
        index=True
    )
    transcription_text = Column(Text, nullable=True)
    transcription_segments = Column(JSON, nullable=True)  # Structured transcription with speaker roles
    transcription_error = Column(Text, nullable=True)

    # Analysis fields
    analysis_status = Column(
        String(20),
        default=AnalysisStatus.PENDING,
        nullable=False,
        index=True
    )
    analysis_result = Column(JSON, nullable=True)
    analysis_error = Column(Text, nullable=True)

    # NEW: Quality scoring fields
    quality_score = Column(Integer, nullable=True, index=True)  # 0-100
    quality_analysis = Column(JSON, nullable=True)
    quality_evaluated_at = Column(DATETIME, nullable=True)

    # Convenience property for duration
    @property
    def duration(self):
        return self.duration_seconds

    # Relationships
    manager = relationship("Manager", back_populates="calls")
    commitments = relationship("Commitment", back_populates="call")

    __table_args__ = (
        Index("idx_calls_manager_created", "manager_id", "created_at"),
        Index("idx_calls_status", "transcription_status", "analysis_status"),
        Index("idx_calls_quality", "quality_score", "created_at"),
        CheckConstraint("duration_seconds >= 0", name="check_duration_positive"),
        CheckConstraint("quality_score >= 0 AND quality_score <= 100", name="check_quality_score_range"),
    )


class Manager(Base, TimestampMixin):
    """Sales managers from AmoCRM"""
    __tablename__ = "managers"

    id = Column(Integer, primary_key=True)
    amocrm_user_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    telegram_chat_id = Column(String(50), nullable=True, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_monitored = Column(Boolean, default=True, nullable=False, index=True)  # Monitor by default

    # Relationships
    calls = relationship("Call", back_populates="manager")
    reports = relationship("Report", back_populates="manager")
    commitments = relationship("Commitment", back_populates="manager")

    __table_args__ = (
        Index("idx_managers_active", "is_active", "created_at"),
    )


class AnalysisCache(Base, TimestampMixin):
    """Cache for analysis results to avoid reprocessing"""
    __tablename__ = "analysis_cache"
    
    id = Column(Integer, primary_key=True)
    text_hash = Column(String(64), unique=True, nullable=False, index=True)
    analysis_type = Column(String(50), nullable=False, index=True)
    result = Column(JSON, nullable=False)
    expires_at = Column(DATETIME, nullable=False, index=True)
    
    __table_args__ = (
        Index("idx_cache_type_expires", "analysis_type", "expires_at"),
    )


class Report(Base, TimestampMixin):
    """Generated reports"""
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True)
    report_type = Column(String(20), nullable=False, index=True)
    manager_id = Column(Integer, ForeignKey("managers.id"), nullable=True, index=True)
    date_from = Column(DATETIME, nullable=False, index=True)
    date_to = Column(DATETIME, nullable=False, index=True)
    data = Column(JSON, nullable=False)
    file_path = Column(String(500), nullable=True)
    
    # Relationships
    manager = relationship("Manager", back_populates="reports")
    
    __table_args__ = (
        Index("idx_reports_date_range", "date_from", "date_to"),
        Index("idx_reports_manager_type", "manager_id", "report_type"),
    )


class SystemLog(Base, TimestampMixin):
    """System logs for monitoring and debugging"""
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True)
    level = Column(String(20), nullable=False, index=True)
    message = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)
    source = Column(String(100), nullable=True, index=True)
    
    __table_args__ = (
        Index("idx_logs_level_created", "level", "created_at"),
        Index("idx_logs_source_created", "source", "created_at"),
    )


class TokenStorage(Base, TimestampMixin):
    """Storage for AmoCRM tokens and other sensitive data"""
    __tablename__ = "token_storage"

    id = Column(Integer, primary_key=True)
    service = Column(String(50), nullable=False, index=True)
    token_type = Column(String(50), nullable=False)
    encrypted_token = Column(Text, nullable=False)
    expires_at = Column(DATETIME, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("service", "token_type", name="uq_service_token_type"),
        Index("idx_tokens_expires", "expires_at"),
    )


class Commitment(Base, TimestampMixin):
    """Commitments/promises made by managers to clients"""
    __tablename__ = "commitments"

    id = Column(Integer, primary_key=True)
    call_id = Column(GUID(), ForeignKey("calls.id"), nullable=True, index=True)
    deal_id = Column(Integer, nullable=False, index=True)
    manager_id = Column(Integer, ForeignKey("managers.id"), nullable=False, index=True)

    # Commitment details
    commitment_text = Column(Text, nullable=False)
    deadline = Column(DATETIME, nullable=False, index=True)
    category = Column(String(50), nullable=True, index=True)  # document, call, meeting, etc
    priority = Column(String(20), nullable=True, index=True)  # high, medium, low

    # Status
    is_fulfilled = Column(Boolean, default=False, nullable=False, index=True)
    fulfilled_at = Column(DATETIME, nullable=True)
    is_overdue = Column(Boolean, default=False, nullable=False, index=True)

    # Reminders
    reminder_sent = Column(Boolean, default=False, nullable=False)
    escalated_to_manager = Column(Boolean, default=False, nullable=False)

    # Relationships
    call = relationship("Call", back_populates="commitments")
    manager = relationship("Manager", back_populates="commitments")

    __table_args__ = (
        Index("idx_commitments_manager_deadline", "manager_id", "deadline"),
        Index("idx_commitments_status", "is_fulfilled", "is_overdue"),
        Index("idx_commitments_deal", "deal_id", "deadline"),
    )


class User(Base, TimestampMixin):
    """Client users with access to dashboard"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)

    # Subscription
    is_active = Column(Boolean, default=True, nullable=False)
    subscription_plan = Column(String(50), default="trial", nullable=False)  # trial, basic, pro
    subscription_expires_at = Column(DATETIME, nullable=True)

    # Settings
    amocrm_integration_enabled = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_active", "is_active", "subscription_expires_at"),
    )


class AlertSettings(Base, TimestampMixin):
    """Alert settings for monitoring and notifications"""
    __tablename__ = "alert_settings"

    id = Column(Integer, primary_key=True)

    # Quality thresholds
    min_quality_score = Column(Integer, default=70, nullable=False)  # Alert if quality < this

    # Call duration thresholds
    min_call_duration = Column(Integer, default=60, nullable=False)  # seconds
    max_call_duration = Column(Integer, default=1800, nullable=False)  # seconds (30 min)

    # Response time alerts
    max_response_time_hours = Column(Integer, default=24, nullable=False)

    # Keyword alerts (JSON list of keywords to monitor)
    alert_keywords = Column(JSON, nullable=True)  # ["возврат", "жалоба", "руководитель"]

    # Notification settings
    notify_on_low_quality = Column(Boolean, default=True, nullable=False)
    notify_on_missed_commitment = Column(Boolean, default=True, nullable=False)
    notify_on_keywords = Column(Boolean, default=True, nullable=False)
    notify_on_long_silence = Column(Boolean, default=False, nullable=False)

    # Daily digest
    send_daily_digest = Column(Boolean, default=True, nullable=False)
    digest_time = Column(String(5), default="09:00", nullable=False)  # HH:MM format

    # Working hours monitoring
    working_hours_start = Column(String(5), default="09:00", nullable=False)
    working_hours_end = Column(String(5), default="18:00", nullable=False)
    alert_outside_hours = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint("min_quality_score >= 0 AND min_quality_score <= 100", name="check_quality_range"),
    )