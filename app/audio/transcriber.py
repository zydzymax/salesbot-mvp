"""
OpenAI Whisper API integration for audio transcription
Handles API calls, retries, and error handling
"""

import io
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import httpx
import structlog

from ..config import get_settings
from ..utils.helpers import retry_async

logger = structlog.get_logger("salesbot.audio.transcriber")


@dataclass
class TranscriptionSegment:
    """Transcription segment with timing"""
    start_time: float
    end_time: float
    text: str


class WhisperTranscriber:
    """OpenAI Whisper API client for transcription"""
    
    def __init__(self):
        self.settings = get_settings()
        self.api_url = "https://api.openai.com/v1/audio/transcriptions"
        
    async def transcribe(
        self,
        audio_data: bytes,
        language: str = "ru",
        response_format: str = "text",
        temperature: float = 0.0
    ) -> Optional[str]:
        """Transcribe audio using Whisper API"""
        
        if not self.settings.openai_api_key:
            logger.error("OpenAI API key not configured")
            return None
        
        logger.info(f"Starting transcription", audio_size=len(audio_data), language=language)
        
        try:
            # Use retry wrapper for API calls
            result = await retry_async(
                lambda: self._make_transcription_request(
                    audio_data, language, response_format, temperature
                ),
                max_retries=3,
                delay=1.0,
                backoff_factor=2.0,
                exceptions=(httpx.HTTPError,)
            )
            
            if result:
                logger.info(f"Transcription completed", length=len(result))
                return result
            else:
                logger.error("Transcription returned empty result")
                return None
                
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None
    
    async def transcribe_with_timestamps(
        self,
        audio_data: bytes,
        language: str = "ru"
    ) -> List[TranscriptionSegment]:
        """Transcribe audio with word-level timestamps"""
        
        if not self.settings.openai_api_key:
            logger.error("OpenAI API key not configured")
            return []
        
        logger.info(f"Starting transcription with timestamps", audio_size=len(audio_data))
        
        try:
            result = await retry_async(
                lambda: self._make_transcription_request(
                    audio_data, language, "verbose_json", 0.0
                ),
                max_retries=3,
                delay=1.0,
                backoff_factor=2.0,
                exceptions=(httpx.HTTPError,)
            )
            
            if not result:
                return []
            
            segments = []
            if isinstance(result, dict) and "segments" in result:
                for segment_data in result["segments"]:
                    segment = TranscriptionSegment(
                        start_time=segment_data.get("start", 0.0),
                        end_time=segment_data.get("end", 0.0),
                        text=segment_data.get("text", "").strip()
                    )
                    if segment.text:
                        segments.append(segment)
            
            logger.info(f"Segmented transcription completed", segments=len(segments))
            return segments
            
        except Exception as e:
            logger.error(f"Segmented transcription failed: {e}")
            return []
    
    async def _make_transcription_request(
        self,
        audio_data: bytes,
        language: str,
        response_format: str,
        temperature: float
    ) -> Optional[Any]:
        """Make actual API request to Whisper"""
        
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}"
        }
        
        # Prepare form data
        files = {
            "file": ("audio.mp3", io.BytesIO(audio_data), "audio/mpeg"),
            "model": (None, "whisper-1"),
            "language": (None, language),
            "response_format": (None, response_format),
            "temperature": (None, str(temperature))
        }
        
        # Add optional parameters for better Russian transcription
        if language == "ru":
            files["prompt"] = (None, "Расшифровка телефонного разговора менеджера по продажам с клиентом.")
        
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minute timeout
            try:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    files=files
                )
                
                logger.info(
                    f"Whisper API request completed",
                    status_code=response.status_code,
                    response_size=len(response.content)
                )
                
                response.raise_for_status()
                
                if response_format == "text":
                    return response.text.strip()
                else:
                    return response.json()
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Rate limit hit, will retry")
                    raise
                elif e.response.status_code == 400:
                    error_text = e.response.text
                    logger.error(f"Bad request: {error_text}")
                    return None
                else:
                    logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                    raise
            except httpx.TimeoutException:
                logger.error("Transcription request timed out")
                raise
            except Exception as e:
                logger.error(f"Unexpected error in transcription request: {e}")
                raise
    
    async def validate_transcription(self, transcription: str) -> bool:
        """Validate transcription quality"""
        if not transcription:
            return False
        
        # Basic validation checks
        transcription = transcription.strip()
        
        # Too short
        if len(transcription) < 10:
            logger.warning("Transcription too short")
            return False
        
        # Too repetitive (same word/phrase repeated many times)
        words = transcription.lower().split()
        if len(words) > 5:
            word_counts = {}
            for word in words:
                word_counts[word] = word_counts.get(word, 0) + 1
            
            max_count = max(word_counts.values())
            if max_count > len(words) * 0.5:  # More than 50% repetition
                logger.warning("Transcription too repetitive")
                return False
        
        # Check for common transcription errors
        error_indicators = [
            "спасибо за просмотр",  # YouTube-like content
            "подписывайтесь на канал",
            "[музыка]",
            "[неразборчиво]" * 3,  # Too many unrecognizable parts
        ]
        
        transcription_lower = transcription.lower()
        for indicator in error_indicators:
            if indicator in transcription_lower:
                logger.warning(f"Found error indicator: {indicator}")
                return False
        
        logger.info("Transcription validation passed")
        return True
    
    async def get_transcription_confidence(self, transcription_data: Dict) -> float:
        """Get confidence score from verbose transcription response"""
        if not isinstance(transcription_data, dict):
            return 1.0
        
        segments = transcription_data.get("segments", [])
        if not segments:
            return 1.0
        
        # Calculate average confidence from segments
        total_confidence = 0.0
        total_duration = 0.0
        
        for segment in segments:
            if "avg_logprob" in segment:
                # Convert log probability to confidence (rough approximation)
                confidence = min(1.0, max(0.0, (segment["avg_logprob"] + 1.0)))
                duration = segment.get("end", 0) - segment.get("start", 0)
                
                total_confidence += confidence * duration
                total_duration += duration
        
        if total_duration > 0:
            return total_confidence / total_duration
        else:
            return 1.0
    
    async def transcribe_batch(
        self,
        audio_chunks: List[bytes],
        language: str = "ru"
    ) -> List[str]:
        """Transcribe multiple audio chunks"""
        logger.info(f"Starting batch transcription", chunks=len(audio_chunks))
        
        results = []
        
        for i, chunk in enumerate(audio_chunks):
            logger.info(f"Transcribing chunk {i+1}/{len(audio_chunks)}")
            
            result = await self.transcribe(chunk, language=language)
            results.append(result or "")
        
        # Combine results
        combined = " ".join(filter(None, results))
        
        logger.info(f"Batch transcription completed", total_length=len(combined))
        return results
    
    def estimate_cost(self, audio_duration_seconds: float) -> float:
        """Estimate transcription cost based on duration"""
        # OpenAI Whisper pricing: $0.006 per minute
        cost_per_minute = 0.006
        duration_minutes = audio_duration_seconds / 60.0
        
        return duration_minutes * cost_per_minute
    
    async def health_check(self) -> bool:
        """Check if Whisper API is accessible"""
        if not self.settings.openai_api_key:
            return False
        
        try:
            # Create a minimal test audio (silence)
            test_audio = b'\xff\xfb\x90\x00' + b'\x00' * 100  # Minimal MP3 header + silence
            
            headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Just check if we can connect and get a proper error response
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    files={"file": ("test.mp3", io.BytesIO(test_audio), "audio/mpeg")}
                )
                
                # We expect either success or a 400 error (invalid audio)
                # Both indicate the API is accessible
                return response.status_code in [200, 400]
                
        except Exception as e:
            logger.error(f"Whisper health check failed: {e}")
            return False