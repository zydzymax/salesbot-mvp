"""
Speech-to-text transcription service using Whisper
"""

from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger("salesbot.transcription")


class TranscriptionService:
    """Service for transcribing audio files using Whisper"""

    def __init__(self, model_size: str = "medium"):
        """
        Initialize transcription service

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
                       medium is recommended for good accuracy
        """
        self.model_size = model_size
        self.model = None

        # Context prompt with common business terms
        self.initial_prompt = """Разговор менеджера с клиентом.
Обсуждение производства, продукции, сделки, заказа.
Ключевые слова: менеджер, клиент, производство, компания, заказ,
товар, продукция, сделка, договор, цена, оплата, доставка."""

    def _load_model(self):
        """Lazy load Whisper model"""
        if self.model is None:
            try:
                import whisper
                logger.info(f"Loading Whisper model: {self.model_size}")
                self.model = whisper.load_model(self.model_size)
                logger.info(f"Whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Whisper model", error=str(e))
                raise

    async def transcribe_file(
        self,
        audio_path: str,
        language: str = "ru",
        post_process: bool = True
    ) -> Optional[dict]:
        """
        Transcribe audio file to text with optional GPT post-processing

        Args:
            audio_path: Path to audio file
            language: Language code (default: ru for Russian)
            post_process: Use GPT to fix transcription errors

        Returns:
            Dict with transcription result or None if failed
        """
        try:
            # Load model if not already loaded
            self._load_model()

            # Check if file exists
            if not Path(audio_path).exists():
                logger.error(f"Audio file not found", path=audio_path)
                return None

            logger.info(f"Starting transcription", path=audio_path, language=language)

            # Transcribe with context prompt
            result = self.model.transcribe(
                audio_path,
                language=language,
                initial_prompt=self.initial_prompt,
                verbose=False
            )

            text = result["text"].strip()

            logger.info(
                f"Transcription completed",
                path=audio_path,
                text_length=len(text),
                language=result.get("language", language)
            )

            # Optional: Post-process with GPT to fix errors
            if post_process:
                corrected_text = await self._post_process_with_gpt(text)
                if corrected_text:
                    logger.info(
                        "Post-processing applied",
                        original_length=len(text),
                        corrected_length=len(corrected_text)
                    )
                    text = corrected_text

            return {
                "text": text,
                "language": result.get("language", language),
                "segments": result.get("segments", [])
            }

        except Exception as e:
            logger.error(f"Transcription failed", path=audio_path, error=str(e))
            return None

    async def _post_process_with_gpt(self, text: str) -> Optional[str]:
        """Use GPT to correct obvious transcription errors"""
        try:
            from openai import AsyncOpenAI
            from ..config import get_settings

            settings = get_settings()
            if not settings.openai_api_key:
                return None

            client = AsyncOpenAI(api_key=settings.openai_api_key)

            prompt = f"""Исправь ошибки распознавания речи в тексте разговора.
Сохрани смысл и структуру. Исправь только явные ошибки распознавания.

Текст: {text}

Исправленный текст:"""

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2000
            )

            corrected = response.choices[0].message.content.strip()
            return corrected

        except Exception as e:
            logger.warning(f"Post-processing failed, using original", error=str(e))
            return None


# Global service instance
# Using 'medium' model - best balance of accuracy and resource usage
# (large requires 10GB+ RAM which may not be available)
transcription_service = TranscriptionService(model_size="medium")
