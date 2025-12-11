"""
Configuration management with Pydantic Settings
Loads from .env file with validation and defaults
"""

import os
from typing import Optional
from pydantic import validator, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with validation"""
    
    # AmoCRM Configuration
    amocrm_subdomain: str = Field(..., description="AmoCRM subdomain")
    amocrm_client_id: str = Field(..., description="AmoCRM Client ID")
    amocrm_client_secret: str = Field(..., description="AmoCRM Client Secret")
    amocrm_redirect_uri: str = Field(..., description="AmoCRM Redirect URI")
    amocrm_access_token: Optional[str] = Field(None, description="AmoCRM Access Token")
    amocrm_refresh_token: Optional[str] = Field(None, description="AmoCRM Refresh Token")
    
    # API Keys (to be added later)
    openai_api_key: Optional[str] = Field(None, description="OpenAI API Key")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model for analysis (gpt-4o, gpt-4-turbo, o1, o1-mini)")
    telegram_bot_token: Optional[str] = Field(None, description="Telegram Bot Token")
    telegram_admin_chat_ids: Optional[str] = Field(None, description="Telegram Admin Chat IDs (JSON list)")
    
    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./salesbot.db",
        description="Database connection URL"
    )
    
    # Redis
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis connection URL"
    )
    
    # Security
    secret_key: str = Field(..., description="JWT Secret Key")
    encryption_key: str = Field(..., description="Data encryption key (32 chars)")
    
    # Application Limits
    max_calls_per_day: int = Field(default=50, description="Max calls to process per day")
    max_audio_duration_seconds: int = Field(
        default=300, 
        description="Max audio duration in seconds"
    )
    cache_ttl_seconds: int = Field(
        default=86400, 
        description="Cache TTL in seconds"
    )
    max_workers: int = Field(default=2, description="Max async workers")
    max_queue_size: int = Field(default=100, description="Max queue size")
    
    # Rate Limiting
    api_rate_limit: int = Field(default=10, description="API requests per second")
    amocrm_rate_limit: int = Field(default=7, description="AmoCRM requests per second")
    
    # Environment
    environment: str = Field(default="development", description="Environment")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Log level")
    
    # Paths
    audio_storage_path: str = Field(
        default="/tmp/salesbot/audio",
        description="Audio files storage path"
    )
    log_path: str = Field(
        default="/var/log/salesbot",
        description="Log files path"
    )
    
    @validator("encryption_key")
    def validate_encryption_key(cls, v):
        if len(v) != 32:
            raise ValueError("Encryption key must be exactly 32 characters")
        return v
    
    @validator("environment")
    def validate_environment(cls, v):
        if v not in ["development", "production", "testing"]:
            raise ValueError("Environment must be development, production, or testing")
        return v
    
    @validator("log_level")
    def validate_log_level(cls, v):
        if v not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError("Invalid log level")
        return v
    
    @property
    def is_development(self) -> bool:
        return self.environment == "development"
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def amocrm_base_url(self) -> str:
        return f"https://{self.amocrm_subdomain}.amocrm.ru"
    
    def create_directories(self):
        """Create necessary directories"""
        os.makedirs(self.audio_storage_path, exist_ok=True)
        os.makedirs(self.log_path, exist_ok=True)
    
    model_config = {
        "extra": "ignore",  # Ignore extra fields from .env
        "env_file": ".env",
        "case_sensitive": False
    }


# Global settings instance
settings = Settings()

# Create directories on import
try:
    settings.create_directories()
except Exception as e:
    print(f"Warning: Could not create directories: {e}")


def get_settings() -> Settings:
    """Get application settings"""
    return settings