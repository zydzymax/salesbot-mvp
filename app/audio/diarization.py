"""
Speaker Diarization using pyannote.audio
Identifies who speaks when in audio recordings
"""

import tempfile
import os
from typing import List, Dict, Tuple
from dataclasses import dataclass

import structlog

logger = structlog.get_logger("salesbot.audio.diarization")


@dataclass
class SpeakerSegment:
    """Speaker segment with timing"""
    speaker: str  # "SPEAKER_00", "SPEAKER_01", etc.
    start_time: float
    end_time: float


class SpeakerDiarizer:
    """Speaker diarization using pyannote.audio"""

    def __init__(self, hf_token: str = None):
        """
        Initialize diarizer

        Args:
            hf_token: HuggingFace API token (optional, needed for some models)
        """
        self.hf_token = hf_token
        self.pipeline = None

    async def initialize(self):
        """Initialize the diarization pipeline"""
        if self.pipeline is not None:
            return

        try:
            from pyannote.audio import Pipeline

            # Try to load the pre-trained diarization model
            # This model works without HF token
            try:
                self.pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=self.hf_token
                )
                logger.info("Loaded pyannote speaker-diarization-3.1 model")
            except Exception as e:
                logger.warning(f"Failed to load model with auth: {e}")
                # Try without token
                self.pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1"
                )
                logger.info("Loaded model without auth token")

        except Exception as e:
            logger.error(f"Failed to initialize diarization pipeline: {e}")
            raise

    async def diarize_audio(
        self,
        audio_data: bytes,
        num_speakers: int = 2
    ) -> List[SpeakerSegment]:
        """
        Perform speaker diarization on audio

        Args:
            audio_data: Audio file bytes (mp3, wav, etc)
            num_speakers: Expected number of speakers (default: 2 for manager+client)

        Returns:
            List of speaker segments with timing
        """
        await self.initialize()

        if self.pipeline is None:
            logger.error("Diarization pipeline not initialized")
            return []

        # Save audio to temporary file (pyannote requires file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(audio_data)

        try:
            logger.info(f"Starting diarization", audio_size=len(audio_data))

            # Run diarization
            diarization = self.pipeline(
                tmp_path,
                num_speakers=num_speakers
            )

            # Extract segments
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segment = SpeakerSegment(
                    speaker=speaker,
                    start_time=turn.start,
                    end_time=turn.end
                )
                segments.append(segment)

            logger.info(
                f"Diarization completed",
                segments=len(segments),
                speakers=len(set(s.speaker for s in segments))
            )

            return segments

        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            return []
        finally:
            # Cleanup temp file
            try:
                os.unlink(tmp_path)
            except:
                pass

    def assign_roles(
        self,
        segments: List[SpeakerSegment],
        call_direction: str = "outgoing"
    ) -> List[SpeakerSegment]:
        """
        Assign roles (manager/client) to speakers based on call direction

        Args:
            segments: Speaker segments from diarization
            call_direction: "outgoing" (manager calls) or "incoming" (client calls)

        Returns:
            Segments with roles assigned as "manager" or "client"
        """
        if not segments:
            return []

        # Find unique speakers
        speakers = list(set(s.speaker for s in segments))

        if len(speakers) == 0:
            return []

        # Determine which speaker is manager based on who speaks first
        first_speaker = segments[0].speaker

        if call_direction == "outgoing":
            # Outgoing call: first speaker is usually manager (greeting)
            manager_speaker = first_speaker
        else:
            # Incoming call: first speaker is usually client
            manager_speaker = speakers[1] if len(speakers) > 1 else speakers[0]

        # Assign roles
        role_segments = []
        for segment in segments:
            role = "manager" if segment.speaker == manager_speaker else "client"
            role_segment = SpeakerSegment(
                speaker=role,
                start_time=segment.start_time,
                end_time=segment.end_time
            )
            role_segments.append(role_segment)

        logger.info(
            f"Roles assigned",
            manager_segments=sum(1 for s in role_segments if s.speaker == "manager"),
            client_segments=sum(1 for s in role_segments if s.speaker == "client")
        )

        return role_segments

    def merge_consecutive_segments(
        self,
        segments: List[SpeakerSegment]
    ) -> List[SpeakerSegment]:
        """
        Merge consecutive segments from the same speaker

        Args:
            segments: List of speaker segments

        Returns:
            Merged segments
        """
        if not segments:
            return []

        merged = []
        current = segments[0]

        for segment in segments[1:]:
            if segment.speaker == current.speaker:
                # Merge with current
                current = SpeakerSegment(
                    speaker=current.speaker,
                    start_time=current.start_time,
                    end_time=segment.end_time
                )
            else:
                # Different speaker, save current and start new
                merged.append(current)
                current = segment

        # Don't forget last segment
        merged.append(current)

        logger.info(f"Merged segments: {len(segments)} -> {len(merged)}")
        return merged


# Global instance
diarizer = SpeakerDiarizer()
