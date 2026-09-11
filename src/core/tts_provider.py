"""
Text-to-speech provider abstraction.
Supports ElevenLabs (v1), with the abstraction ready for other providers.
"""

import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from .secrets import get_secret_value


def _load_elevenlabs_key() -> str:
    """
    Load ElevenLabs API key from AWS Secrets Manager or env var.

    Priority:
    1. AWS Secrets Manager (same secret as Kling credentials)
    2. ELEVENLABS_API_KEY env var
    """
    key = get_secret_value("ELEVENLABS_API_KEY", ("ELEVENLABS_API_KEY", "elevenlabs_api_key", "eleven_labs_secret"))
    if key:
        return key

    raise ValueError(
        "ElevenLabs API key not found. Either:\n"
        "  1. Add 'ELEVENLABS_API_KEY' or 'elevenlabs_api_key' to your AWS Secrets Manager secret, or\n"
        "  2. Set ELEVENLABS_API_KEY env var in .env"
    )


class TTSProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: str = "default",
    ) -> tuple[str, float]:
        """
        Synthesize text to speech.

        Args:
            text: Text to speak
            voice_id: Voice identifier

        Returns:
            Tuple of (audio_file_path, duration_seconds)
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class ElevenLabsProvider(TTSProvider):
    """
    ElevenLabs text-to-speech.
    High quality, ~$0.01-0.05 per clip depending on text length.
    """

    BASE_URL = "https://api.elevenlabs.io/v1"
    # Default voice: "Rachel" — clear, professional female voice
    DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

    def __init__(
        self,
        api_key: str | None = None,
        output_dir: str = "output/videos/audio",
    ):
        self.api_key = api_key or _load_elevenlabs_key()

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def synthesize(
        self,
        text: str,
        voice_id: str = "default",
    ) -> tuple[str, float]:
        """Synthesize text to speech using ElevenLabs."""
        if voice_id == "default":
            voice_id = self.DEFAULT_VOICE_ID

        response = self.client.post(
            f"/text-to-speech/{voice_id}",
            json={
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            },
            headers={"Accept": "audio/mpeg"},
        )
        response.raise_for_status()

        # Save audio file
        filename = f"voiceover_{uuid.uuid4().hex[:8]}.mp3"
        path = self.output_dir / filename

        with open(path, 'wb') as f:
            f.write(response.content)

        # Estimate duration from file size (rough: mp3 at ~128kbps)
        file_size = len(response.content)
        estimated_duration = file_size / (128 * 1000 / 8)  # bytes / (bitrate in bytes/sec)

        print(f"  Voiceover saved: {path} (~{estimated_duration:.1f}s)")
        return str(path), estimated_duration

    @property
    def name(self) -> str:
        return "elevenlabs"

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_tts_provider(name: str = "elevenlabs") -> TTSProvider:
    """Factory function to get a TTS provider by name."""
    providers = {
        "elevenlabs": ElevenLabsProvider,
    }
    if name not in providers:
        available = ", ".join(providers.keys())
        raise ValueError(f"Unknown TTS provider: {name}. Available: {available}")
    return providers[name]()
