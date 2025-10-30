"""
Audio processing utilities
Compression, validation, format conversion for Whisper API
"""

import io
import os
import tempfile
from typing import Optional, List, Tuple
import asyncio

import structlog
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from ..config import get_settings
from ..utils.helpers import format_file_size, ensure_directory_exists

logger = structlog.get_logger("salesbot.audio.processor")


class AudioProcessor:
    """Handle audio file processing and validation"""
    
    def __init__(self):
        self.settings = get_settings()
        self.max_file_size = 25 * 1024 * 1024  # 25MB Whisper limit
        self.target_sample_rate = 16000  # 16kHz for speech
        self.supported_formats = [
            'mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm', 'ogg', 'flac'
        ]
    
    async def process_for_transcription(self, audio_data: bytes) -> Optional[bytes]:
        """Process audio data for Whisper transcription"""
        logger.info(f"Processing audio", size=format_file_size(len(audio_data)))
        
        try:
            # Validate input
            if not self.validate_audio_data(audio_data):
                logger.error("Audio validation failed")
                return None
            
            # Load audio
            audio = await self._load_audio_from_bytes(audio_data)
            if not audio:
                return None
            
            # Get duration before processing
            duration = len(audio) / 1000.0  # Duration in seconds
            logger.info(f"Audio duration: {duration:.2f}s")
            
            # Check duration limit
            if duration > self.settings.max_audio_duration_seconds:
                logger.error(f"Audio too long: {duration}s > {self.settings.max_audio_duration_seconds}s")
                return None
            
            # Process audio
            processed_audio = await self._optimize_for_speech(audio)
            
            # Convert to bytes
            output_buffer = io.BytesIO()
            processed_audio.export(output_buffer, format="mp3", bitrate="64k")
            processed_data = output_buffer.getvalue()
            
            logger.info(
                f"Audio processed successfully",
                original_size=format_file_size(len(audio_data)),
                processed_size=format_file_size(len(processed_data)),
                compression_ratio=f"{len(processed_data)/len(audio_data):.2f}"
            )
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Audio processing failed: {e}")
            return None
    
    def validate_audio_data(self, audio_data: bytes) -> bool:
        """Validate audio data"""
        if not audio_data:
            logger.error("Empty audio data")
            return False
        
        if len(audio_data) > self.max_file_size:
            logger.error(f"File too large: {format_file_size(len(audio_data))} > 25MB")
            return False
        
        # Check for basic audio file headers
        audio_headers = [
            b'ID3',      # MP3
            b'RIFF',     # WAV
            b'OggS',     # OGG
            b'fLaC',     # FLAC
            b'\x00\x00\x00\x20ftypM4A',  # M4A
        ]
        
        has_valid_header = any(audio_data.startswith(header) for header in audio_headers)
        if not has_valid_header:
            # Check for MP3 without ID3 tag
            if len(audio_data) > 2 and audio_data[0:2] == b'\xff\xfb':
                has_valid_header = True
        
        if not has_valid_header:
            logger.warning("Unknown audio format, attempting to process anyway")
        
        return True
    
    async def _load_audio_from_bytes(self, audio_data: bytes) -> Optional[AudioSegment]:
        """Load audio from bytes"""
        try:
            # Try different formats
            formats_to_try = ['mp3', 'wav', 'mp4', 'ogg', 'flac']
            
            for fmt in formats_to_try:
                try:
                    audio = AudioSegment.from_file(io.BytesIO(audio_data), format=fmt)
                    logger.info(f"Successfully loaded audio as {fmt}")
                    return audio
                except CouldntDecodeError:
                    continue
            
            # If all formats fail, try without specifying format
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            logger.info("Successfully loaded audio with auto-detection")
            return audio
            
        except Exception as e:
            logger.error(f"Failed to load audio: {e}")
            return None
    
    async def _optimize_for_speech(self, audio: AudioSegment) -> AudioSegment:
        """Optimize audio for speech recognition"""
        try:
            # Convert to mono if stereo
            if audio.channels > 1:
                audio = audio.set_channels(1)
                logger.info("Converted to mono")
            
            # Resample to 16kHz if needed
            if audio.frame_rate != self.target_sample_rate:
                audio = audio.set_frame_rate(self.target_sample_rate)
                logger.info(f"Resampled to {self.target_sample_rate}Hz")
            
            # Normalize volume (gentle)
            if audio.max_possible_amplitude > 0:
                # Normalize to -6dB to avoid clipping
                target_dBFS = -6.0
                change_in_dBFS = target_dBFS - audio.dBFS
                
                # Only amplify if the audio is too quiet
                if change_in_dBFS > 0 and change_in_dBFS < 20:
                    audio = audio + change_in_dBFS
                    logger.info(f"Normalized volume (+{change_in_dBFS:.1f}dB)")
            
            # Remove silence from beginning and end
            audio = self._trim_silence(audio)
            
            return audio
            
        except Exception as e:
            logger.error(f"Audio optimization failed: {e}")
            return audio  # Return original if optimization fails
    
    def _trim_silence(self, audio: AudioSegment, silence_thresh: int = -40) -> AudioSegment:
        """Trim silence from beginning and end"""
        try:
            # Find first and last non-silent parts
            non_silent_ranges = self._detect_non_silent(audio, silence_thresh=silence_thresh)
            
            if not non_silent_ranges:
                return audio  # No non-silent parts found
            
            # Get start and end of audio content
            start_time = non_silent_ranges[0][0]
            end_time = non_silent_ranges[-1][1]
            
            # Trim with small padding
            padding = 100  # 100ms padding
            start_time = max(0, start_time - padding)
            end_time = min(len(audio), end_time + padding)
            
            trimmed = audio[start_time:end_time]
            
            if len(trimmed) < len(audio):
                logger.info(f"Trimmed silence: {len(audio)}ms -> {len(trimmed)}ms")
            
            return trimmed
            
        except Exception as e:
            logger.error(f"Silence trimming failed: {e}")
            return audio
    
    def _detect_non_silent(
        self, 
        audio: AudioSegment, 
        silence_thresh: int = -40,
        chunk_size: int = 100
    ) -> List[Tuple[int, int]]:
        """Detect non-silent ranges in audio"""
        non_silent_ranges = []
        current_start = None
        
        for i in range(0, len(audio), chunk_size):
            chunk = audio[i:i + chunk_size]
            
            if chunk.dBFS > silence_thresh:
                if current_start is None:
                    current_start = i
            else:
                if current_start is not None:
                    non_silent_ranges.append((current_start, i))
                    current_start = None
        
        # Handle case where audio ends with non-silence
        if current_start is not None:
            non_silent_ranges.append((current_start, len(audio)))
        
        return non_silent_ranges
    
    def get_audio_duration(self, audio_data: bytes) -> int:
        """Get audio duration in seconds"""
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            return int(len(audio) / 1000)
        except Exception:
            return 0
    
    def get_audio_info(self, audio_data: bytes) -> dict:
        """Get detailed audio information"""
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            
            return {
                "duration_seconds": len(audio) / 1000.0,
                "sample_rate": audio.frame_rate,
                "channels": audio.channels,
                "bit_depth": audio.sample_width * 8,
                "file_size": len(audio_data),
                "format": "detected"
            }
        except Exception as e:
            return {"error": str(e)}
    
    async def split_long_audio(
        self, 
        audio_data: bytes, 
        max_duration_seconds: int
    ) -> List[bytes]:
        """Split long audio into smaller chunks"""
        try:
            audio = await self._load_audio_from_bytes(audio_data)
            if not audio:
                return []
            
            duration = len(audio) / 1000.0
            if duration <= max_duration_seconds:
                return [audio_data]  # No need to split
            
            chunks = []
            chunk_duration_ms = max_duration_seconds * 1000
            
            for start in range(0, len(audio), chunk_duration_ms):
                end = min(start + chunk_duration_ms, len(audio))
                chunk = audio[start:end]
                
                # Export chunk to bytes
                buffer = io.BytesIO()
                chunk.export(buffer, format="mp3", bitrate="64k")
                chunks.append(buffer.getvalue())
            
            logger.info(f"Split audio into {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            logger.error(f"Audio splitting failed: {e}")
            return []
    
    async def save_audio_file(self, audio_data: bytes, filename: str) -> Optional[str]:
        """Save audio data to file"""
        try:
            ensure_directory_exists(self.settings.audio_storage_path)
            
            file_path = os.path.join(self.settings.audio_storage_path, filename)
            
            with open(file_path, 'wb') as f:
                f.write(audio_data)
            
            logger.info(f"Audio saved", file_path=file_path, size=format_file_size(len(audio_data)))
            return file_path
            
        except Exception as e:
            logger.error(f"Failed to save audio file: {e}")
            return None