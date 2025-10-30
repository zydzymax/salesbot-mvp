"""
Helper utilities and common functions
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union
import json

import structlog

logger = structlog.get_logger("salesbot.helpers")


def ensure_directory_exists(path: str) -> bool:
    """Ensure directory exists, create if not"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        return False


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """Safely parse JSON string"""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any, default: str = "{}") -> str:
    """Safely serialize to JSON string"""
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return default


def format_duration(seconds: int) -> str:
    """Format duration in human readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def format_file_size(bytes_size: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to maximum length"""
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def extract_phone_digits(phone: str) -> str:
    """Extract only digits from phone number"""
    if not phone:
        return ""
    return ''.join(filter(str.isdigit, phone))


def format_phone_number(phone: str) -> str:
    """Format phone number for display"""
    digits = extract_phone_digits(phone)
    
    if len(digits) == 11 and digits.startswith('7'):
        # Russian format: +7 (XXX) XXX-XX-XX
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    elif len(digits) == 10:
        # US format: (XXX) XXX-XXXX
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    else:
        return phone  # Return original if can't format


def clean_text_for_analysis(text: str) -> str:
    """Clean text for analysis (remove noise, normalize)"""
    if not text:
        return ""
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    # Remove common noise words/sounds
    noise_patterns = [
        'эм-м', 'а-а', 'э-э', 'м-м',
        '[неразборчиво]', '[пауза]', '[шум]'
    ]
    
    for pattern in noise_patterns:
        text = text.replace(pattern, ' ')
    
    # Clean up extra spaces again
    text = ' '.join(text.split())
    
    return text.strip()


def extract_key_phrases(text: str, min_length: int = 3) -> List[str]:
    """Extract potential key phrases from text"""
    if not text:
        return []
    
    # Simple keyword extraction (in production, use proper NLP)
    words = text.lower().split()
    phrases = []
    
    # Extract 2-3 word phrases
    for i in range(len(words) - 1):
        phrase = ' '.join(words[i:i+2])
        if len(phrase) >= min_length:
            phrases.append(phrase)
    
    # Remove duplicates and sort by length
    phrases = list(set(phrases))
    phrases.sort(key=len, reverse=True)
    
    return phrases[:10]  # Return top 10


def calculate_call_score(
    duration: int,
    transcription_quality: float,
    analysis_scores: Dict[str, float]
) -> float:
    """Calculate overall call score"""
    if not analysis_scores:
        return 0.0
    
    # Duration factor (optimal 2-10 minutes)
    if duration < 30:  # Too short
        duration_factor = 0.5
    elif duration > 600:  # Too long
        duration_factor = 0.8
    else:
        duration_factor = 1.0
    
    # Average analysis scores
    avg_score = sum(analysis_scores.values()) / len(analysis_scores)
    
    # Apply factors
    final_score = avg_score * duration_factor * transcription_quality
    
    return min(100.0, max(0.0, final_score))


async def retry_async(
    coro_func,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Any:
    """Retry async function with exponential backoff"""
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await coro_func()
        except exceptions as e:
            last_exception = e
            
            if attempt == max_retries:
                break
            
            wait_time = delay * (backoff_factor ** attempt)
            logger.warning(
                f"Attempt {attempt + 1} failed, retrying in {wait_time}s",
                error=str(e)
            )
            await asyncio.sleep(wait_time)
    
    raise last_exception


def batch_items(items: List[Any], batch_size: int) -> List[List[Any]]:
    """Split list into batches"""
    batches = []
    for i in range(0, len(items), batch_size):
        batches.append(items[i:i + batch_size])
    return batches


def get_moscow_time() -> datetime:
    """Get current Moscow time"""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Moscow"))


def is_working_hours(dt: Optional[datetime] = None) -> bool:
    """Check if current time is within working hours (9-18 MSK)"""
    if dt is None:
        dt = get_moscow_time()
    
    return 9 <= dt.hour < 18 and dt.weekday() < 5  # Monday = 0, Sunday = 6


def format_analysis_summary(analysis_result: Dict[str, Any]) -> str:
    """Format analysis result for display"""
    if not analysis_result:
        return "Анализ не завершен"
    
    summary_parts = []
    
    # Overall score
    if "overall_score" in analysis_result:
        score = analysis_result["overall_score"]
        summary_parts.append(f"Общая оценка: {score}/100")
    
    # Key strengths
    if "strengths" in analysis_result and analysis_result["strengths"]:
        strengths = ", ".join(analysis_result["strengths"][:2])
        summary_parts.append(f"Сильные стороны: {strengths}")
    
    # Key improvements
    if "improvements" in analysis_result and analysis_result["improvements"]:
        improvements = ", ".join(analysis_result["improvements"][:2])
        summary_parts.append(f"Для улучшения: {improvements}")
    
    return " | ".join(summary_parts) if summary_parts else "Результат анализа недоступен"


class AsyncContextManager:
    """Async context manager helper"""
    
    def __init__(self, async_func, *args, **kwargs):
        self.async_func = async_func
        self.args = args
        self.kwargs = kwargs
        self.resource = None
    
    async def __aenter__(self):
        self.resource = await self.async_func(*self.args, **self.kwargs)
        return self.resource
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self.resource, 'close'):
            if asyncio.iscoroutinefunction(self.resource.close):
                await self.resource.close()
            else:
                self.resource.close()


def measure_time(func_name: str = "operation"):
    """Decorator to measure execution time"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            start_time = datetime.utcnow()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(f"{func_name} completed", duration_seconds=duration)
        
        def sync_wrapper(*args, **kwargs):
            start_time = datetime.utcnow()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(f"{func_name} completed", duration_seconds=duration)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator