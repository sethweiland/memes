"""
Video generation provider abstraction.
Supports Kling AI (v1), with the abstraction layer ready for Runway, Veo, etc.
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from .secrets import get_secret_value


def _load_kling_api_key() -> str:
    """Load the newer single Kling API key, if configured."""
    return get_secret_value("KLING_API_KEY", ("KLING_API_KEY", "kling_api_key"))


def _load_kling_credentials() -> tuple[str, str]:
    """
    Load legacy Kling access_key and secret from AWS Secrets Manager or env vars.

    Priority:
    1. AWS Secrets Manager via BLUEGRASS_SECRET_ARN, APP_SECRET_ARN, or KLING_SECRET_ARN
    2. Env vars / .env values

    Returns:
        Tuple of (access_key, secret)
    """
    access_key = get_secret_value("KLING_ACCESS_KEY", ("KLING_ACCESS_KEY", "kling_access_key"))
    secret = get_secret_value("KLING_SECRET", ("KLING_SECRET", "kling_secret"))
    if access_key and secret:
        return access_key, secret

    raise ValueError(
        "Kling credentials not found. Either:\n"
        "  1. Set KLING_API_KEY in AWS Secrets Manager or .env, or\n"
        "  2. Set legacy KLING_ACCESS_KEY and KLING_SECRET in AWS Secrets Manager or .env"
    )


def _generate_kling_jwt(access_key: str, secret: str) -> str:
    """
    Generate a signed JWT token for Kling API authentication.
    Kling uses access_key + secret to sign a JWT (HS256).
    Token is valid for 30 minutes.
    """
    import hashlib
    import hmac
    import base64

    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "iss": access_key,
        "exp": now + 1800,  # 30 minutes
        "nbf": now - 5,
        "iat": now,
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    signature = hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    sig_b64 = b64url(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


class VideoProvider(ABC):
    """Abstract base class for video generation providers."""

    @abstractmethod
    def generate_clip(
        self,
        prompt: str,
        duration_seconds: float = 5.0,
        aspect_ratio: str = "9:16",
    ) -> tuple[str, float]:
        """
        Generate a video clip from a text prompt.

        Args:
            prompt: Text description of the video to generate
            duration_seconds: Target duration
            aspect_ratio: Aspect ratio ("9:16" vertical, "16:9" horizontal, "1:1" square)

        Returns:
            Tuple of (local_file_path, cost_usd)
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def cost_per_second(self) -> float:
        """Estimated cost per second of generated video."""
        ...


class KlingProvider(VideoProvider):
    """
    Kling AI video generation.
    Cheapest option at ~$0.05-0.10 per second.

    Auth: Prefer the newer KLING_API_KEY. Legacy access_key + secret still works.
    Credentials loaded from AWS Secrets Manager or env vars.

    Uses the Kling API: submit a generation task, poll for completion, download result.
    """

    BASE_URL = "https://api.klingai.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        access_key: str | None = None,
        secret: str | None = None,
        output_dir: str = "output/videos/clips",
    ):
        self._api_key = api_key or _load_kling_api_key()
        self._access_key = ""
        self._secret = ""

        if self._api_key:
            pass
        elif access_key and secret:
            self._access_key = access_key
            self._secret = secret
        else:
            self._access_key, self._secret = _load_kling_credentials()

        self._jwt_token: str = ""
        self._jwt_expires: float = 0

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        # Separate client for downloading (no base_url, longer timeout)
        self._download_client = httpx.Client(timeout=120.0)

    def _get_auth_header(self) -> dict[str, str]:
        """Get Authorization header using API key or a fresh legacy JWT."""
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}

        now = time.time()
        if not self._jwt_token or now >= self._jwt_expires - 60:
            self._jwt_token = _generate_kling_jwt(self._access_key, self._secret)
            self._jwt_expires = now + 1800
        return {"Authorization": f"Bearer {self._jwt_token}"}

    def generate_clip(
        self,
        prompt: str,
        duration_seconds: float = 5.0,
        aspect_ratio: str = "9:16",
    ) -> tuple[str, float]:
        """Submit a video generation task and wait for completion."""
        # Submit the generation task
        task_id = self._submit_task(prompt, duration_seconds, aspect_ratio)

        # Poll until done
        video_url = self._poll_until_done(task_id)

        # Download the result
        local_path = self._download_video(video_url)

        # Estimate cost
        cost = duration_seconds * self.cost_per_second

        return local_path, cost

    def _submit_task(
        self,
        prompt: str,
        duration_seconds: float,
        aspect_ratio: str,
    ) -> str:
        """Submit a video generation task. Returns the task ID."""
        # Map duration to Kling's accepted values
        duration = "5" if duration_seconds <= 5 else "10"

        response = self.client.post(
            "/videos/text2video",
            json={
                "prompt": prompt,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "mode": "std",  # "std" or "pro"
            },
            headers=self._get_auth_header(),
        )
        response.raise_for_status()
        data = response.json()

        task_id = data.get("data", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"Kling API did not return a task_id: {data}")

        print(f"  Kling task submitted: {task_id}")
        return task_id

    def _poll_until_done(
        self,
        task_id: str,
        timeout: int = 300,
        initial_delay: float = 10.0,
    ) -> str:
        """Poll task status until complete. Returns the video URL."""
        start = time.time()
        delay = initial_delay

        while time.time() - start < timeout:
            time.sleep(delay)

            response = self.client.get(
                f"/videos/text2video/{task_id}",
                headers=self._get_auth_header(),
            )
            response.raise_for_status()
            data = response.json()

            task_data = data.get("data", {})
            status = task_data.get("task_status", "")

            if status == "succeed":
                videos = task_data.get("task_result", {}).get("videos", [])
                if videos:
                    return videos[0].get("url", "")
                raise RuntimeError(f"Task succeeded but no video URL in response: {data}")

            if status == "failed":
                reason = task_data.get("task_status_msg", "Unknown error")
                raise RuntimeError(f"Kling generation failed: {reason}")

            # Exponential backoff, capped at 30s
            elapsed = int(time.time() - start)
            print(f"  Kling task {task_id}: {status} ({elapsed}s elapsed)")
            delay = min(delay * 1.5, 30.0)

        raise TimeoutError(f"Kling task {task_id} timed out after {timeout}s")

    def _download_video(self, url: str) -> str:
        """Download video to local directory."""
        filename = f"clip_{uuid.uuid4().hex[:8]}.mp4"
        path = self.output_dir / filename

        response = self._download_client.get(url)
        response.raise_for_status()

        with open(path, 'wb') as f:
            f.write(response.content)

        print(f"  Downloaded clip: {path}")
        return str(path)

    @property
    def name(self) -> str:
        return "kling"

    @property
    def cost_per_second(self) -> float:
        return 0.05  # ~$0.25 for a 5s clip

    def close(self):
        self.client.close()
        self._download_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_provider(name: str = "kling") -> VideoProvider:
    """Factory function to get a video provider by name."""
    providers = {
        "kling": KlingProvider,
    }
    if name not in providers:
        available = ", ".join(providers.keys())
        raise ValueError(f"Unknown video provider: {name}. Available: {available}")
    return providers[name]()
