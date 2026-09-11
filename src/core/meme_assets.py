"""
S3 asset hosting for meme images.

Uploads memes to S3 with public HTTPS URLs for Instagram Graph API.
Automatically converts images to JPEG format if needed.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from PIL import Image

from src.core.secrets import get_secret_value


logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Result of an S3 upload operation."""
    success: bool
    public_url: Optional[str] = None
    s3_key: Optional[str] = None
    error: Optional[str] = None


class MemeAssetUploader:
    """
    Upload meme images to S3 and get public HTTPS URLs.
    
    Configuration (via environment or AWS Secrets Manager):
    - MEME_ASSETS_BUCKET: S3 bucket name
    - MEME_ASSETS_PUBLIC_BASE_URL: Base HTTPS URL for public objects
    - MEME_ASSETS_PUBLIC_PREFIX: Prefix for uploaded objects (default: public/memes/)
    - AWS_DEFAULT_REGION: AWS region (default: us-east-1)
    """
    
    def __init__(
        self,
        bucket: Optional[str] = None,
        public_base_url: Optional[str] = None,
        public_prefix: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """
        Initialize uploader with optional config overrides.
        
        Args:
            bucket: S3 bucket name (defaults to MEME_ASSETS_BUCKET env)
            public_base_url: Base HTTPS URL (defaults to MEME_ASSETS_PUBLIC_BASE_URL env)
            public_prefix: Object key prefix (defaults to MEME_ASSETS_PUBLIC_PREFIX env)
            region: AWS region (defaults to AWS_DEFAULT_REGION env)
        """
        self.bucket = bucket or get_secret_value(
            "MEME_ASSETS_BUCKET",
            secret_keys=["MEME_ASSETS_BUCKET"],
        )
        
        self.public_base_url = public_base_url or get_secret_value(
            "MEME_ASSETS_PUBLIC_BASE_URL",
            secret_keys=["MEME_ASSETS_PUBLIC_BASE_URL"],
        )
        
        self.public_prefix = public_prefix or get_secret_value(
            "MEME_ASSETS_PUBLIC_PREFIX",
            secret_keys=["MEME_ASSETS_PUBLIC_PREFIX"],
            default="public/memes/",
        )
        
        self.region = region or get_secret_value(
            "AWS_DEFAULT_REGION",
            secret_keys=["AWS_DEFAULT_REGION", "AWS_REGION"],
            default="us-east-1",
        )
        
        if not self.bucket:
            raise ValueError(
                "MEME_ASSETS_BUCKET is required. "
                "Set it in .env or AWS Secrets Manager. "
                "See infra/meme-assets/README.md for setup."
            )
        
        if not self.public_base_url:
            # Default to standard S3 URL format
            self.public_base_url = f"https://{self.bucket}.s3.amazonaws.com"
            logger.info(f"Using default public base URL: {self.public_base_url}")
        
        self._s3_client = None
    
    @property
    def s3_client(self):
        """Lazy-load boto3 S3 client."""
        if self._s3_client is None:
            import boto3
            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client
    
    def _ensure_jpeg(
        self,
        image_source: Union[str, Path, bytes, io.BytesIO],
    ) -> io.BytesIO:
        """
        Convert image to JPEG format if needed.
        
        Args:
            image_source: Path to image file, bytes, or BytesIO
        
        Returns:
            BytesIO containing JPEG image data
        """
        # Load image
        if isinstance(image_source, (str, Path)):
            img = Image.open(image_source)
        elif isinstance(image_source, bytes):
            img = Image.open(io.BytesIO(image_source))
        elif isinstance(image_source, io.BytesIO):
            img = Image.open(image_source)
        else:
            raise ValueError(f"Unsupported image source type: {type(image_source)}")
        
        # Convert to RGB if needed (removes alpha channel)
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        
        # Save as JPEG
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=95, optimize=True)
        output.seek(0)
        
        return output
    
    def _generate_key(self, filename: str) -> str:
        """
        Generate S3 key for uploaded object.
        
        Strategy: Use a hash-based filename to avoid collisions and cache busting.
        Format: {prefix}{hash[:12]}_{original_stem}.jpg
        
        Args:
            filename: Original filename
        
        Returns:
            S3 object key
        """
        stem = Path(filename).stem
        # Use filename + timestamp for hash to ensure uniqueness
        import time
        hash_input = f"{filename}_{time.time()}".encode("utf-8")
        hash_hex = hashlib.sha256(hash_input).hexdigest()[:12]
        
        key = f"{self.public_prefix}{hash_hex}_{stem}.jpg"
        return key
    
    def upload(
        self,
        image_source: Union[str, Path, bytes, io.BytesIO],
        filename: Optional[str] = None,
    ) -> UploadResult:
        """
        Upload image to S3 and return public HTTPS URL.
        
        Args:
            image_source: Path to image file, bytes, or BytesIO
            filename: Optional filename for key generation (defaults to image path stem)
        
        Returns:
            UploadResult with success status and public URL
        
        Example:
            >>> uploader = MemeAssetUploader()
            >>> result = uploader.upload("output/memes/my_meme.jpg")
            >>> if result.success:
            ...     print(f"Public URL: {result.public_url}")
        """
        try:
            # Determine filename
            if filename is None:
                if isinstance(image_source, (str, Path)):
                    filename = Path(image_source).name
                else:
                    filename = "meme.jpg"
            
            # Convert to JPEG
            logger.info(f"Converting image to JPEG: {filename}")
            jpeg_data = self._ensure_jpeg(image_source)
            jpeg_bytes = jpeg_data.getvalue()
            
            # Generate S3 key
            s3_key = self._generate_key(filename)
            
            # Upload to S3
            logger.info(f"Uploading to S3: s3://{self.bucket}/{s3_key}")
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=jpeg_bytes,
                ContentType="image/jpeg",
                CacheControl="public, max-age=31536000",  # 1 year cache
            )
            
            # Generate public URL
            public_url = f"{self.public_base_url.rstrip('/')}/{s3_key}"
            
            logger.info(f"Upload successful: {public_url}")
            return UploadResult(
                success=True,
                public_url=public_url,
                s3_key=s3_key,
            )
            
        except Exception as e:
            error = f"Failed to upload image: {e}"
            logger.error(error)
            import traceback
            traceback.print_exc()
            return UploadResult(
                success=False,
                error=error,
            )


# Convenience function for quick uploads
def upload_meme_to_s3(
    image_source: Union[str, Path, bytes, io.BytesIO],
    filename: Optional[str] = None,
) -> UploadResult:
    """
    Convenience function to upload a meme image to S3.
    
    Args:
        image_source: Path to image file, bytes, or BytesIO
        filename: Optional filename for key generation
    
    Returns:
        UploadResult with success status and public URL
    
    Example:
        >>> result = upload_meme_to_s3("output/memes/funny_meme.jpg")
        >>> if result.success:
        ...     print(f"Ready for Instagram: {result.public_url}")
    """
    uploader = MemeAssetUploader()
    return uploader.upload(image_source, filename)


class QueueStorage:
    """
    S3-backed storage for daily candidate queue JSON.
    
    Stores queue metadata in S3 with local file fallback for compatibility.
    Queue files are stored under a non-public prefix: queue/daily-candidates/{date}.json
    """
    
    def __init__(
        self,
        bucket: Optional[str] = None,
        queue_prefix: str = "queue/daily-candidates/",
        local_dir: Optional[Path] = None,
    ):
        """
        Initialize queue storage.
        
        Args:
            bucket: S3 bucket name (defaults to MEME_ASSETS_BUCKET env)
            queue_prefix: S3 prefix for queue files (default: queue/daily-candidates/)
            local_dir: Local directory for cache/fallback (default: data/daily_candidates)
        """
        self.bucket = bucket or get_secret_value(
            "MEME_ASSETS_BUCKET",
            secret_keys=["MEME_ASSETS_BUCKET"],
        )
        self.queue_prefix = queue_prefix
        self.local_dir = local_dir or Path("data/daily_candidates")
        
        self.region = get_secret_value(
            "AWS_DEFAULT_REGION",
            secret_keys=["AWS_DEFAULT_REGION", "AWS_REGION"],
            default="us-east-1",
        )
        
        self._s3_client = None
    
    @property
    def s3_client(self):
        """Lazy-load boto3 S3 client."""
        if self._s3_client is None:
            import boto3
            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client
    
    def _s3_key(self, date_str: str) -> str:
        """Generate S3 key for a queue file."""
        return f"{self.queue_prefix}{date_str}.json"
    
    def _local_path(self, date_str: str) -> Path:
        """Generate local file path for a queue file."""
        return self.local_dir / f"{date_str}.json"
    
    def save(self, date_str: str, data: dict) -> bool:
        """
        Save queue data to S3 and local cache.
        
        Args:
            date_str: Date string (YYYY-MM-DD)
            data: Queue data dict
        
        Returns:
            True if saved to S3, False if only local save succeeded
        """
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        
        # Always save local copy
        self.local_dir.mkdir(parents=True, exist_ok=True)
        local_path = self._local_path(date_str)
        local_path.write_bytes(json_bytes)
        logger.info(f"Saved queue to local: {local_path}")
        
        # Try to save to S3 if bucket is configured
        if not self.bucket:
            logger.warning("S3 bucket not configured, queue saved locally only")
            return False
        
        try:
            s3_key = self._s3_key(date_str)
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json_bytes,
                ContentType="application/json",
            )
            logger.info(f"Saved queue to S3: s3://{self.bucket}/{s3_key}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save queue to S3: {e}")
            return False
    
    def load(self, date_str: str) -> Optional[dict]:
        """
        Load queue data from S3, with local fallback.
        
        Args:
            date_str: Date string (YYYY-MM-DD)
        
        Returns:
            Queue data dict, or None if not found
        """
        # Try S3 first if bucket is configured
        if self.bucket:
            try:
                s3_key = self._s3_key(date_str)
                response = self.s3_client.get_object(
                    Bucket=self.bucket,
                    Key=s3_key,
                )
                data = json.loads(response["Body"].read().decode("utf-8"))
                logger.info(f"Loaded queue from S3: s3://{self.bucket}/{s3_key}")
                return data
            except self.s3_client.exceptions.NoSuchKey:
                logger.debug(f"Queue not found in S3: {s3_key}")
            except Exception as e:
                logger.warning(f"Failed to load queue from S3: {e}")
        
        # Fall back to local file
        local_path = self._local_path(date_str)
        if local_path.exists():
            try:
                data = json.loads(local_path.read_text(encoding="utf-8"))
                logger.info(f"Loaded queue from local: {local_path}")
                return data
            except Exception as e:
                logger.error(f"Failed to load local queue: {e}")
        
        return None
    
    def list_dates(self) -> list[dict]:
        """
        List all available queue dates from S3 and local.
        
        Returns:
            List of date info dicts with date, topic, counts, etc.
        """
        dates_map = {}
        
        # Load from S3 if available
        if self.bucket:
            try:
                response = self.s3_client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=self.queue_prefix,
                )
                for obj in response.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith(".json"):
                        date_str = key.replace(self.queue_prefix, "").replace(".json", "")
                        if date_str not in dates_map:
                            data = self.load(date_str)
                            if data:
                                dates_map[date_str] = self._date_info(date_str, data)
            except Exception as e:
                logger.warning(f"Failed to list S3 queue files: {e}")
        
        # Merge with local files
        if self.local_dir.exists():
            for file_path in self.local_dir.glob("*.json"):
                date_str = file_path.stem
                if date_str not in dates_map:
                    data = self.load(date_str)
                    if data:
                        dates_map[date_str] = self._date_info(date_str, data)
        
        # Sort by date descending
        dates = list(dates_map.values())
        dates.sort(key=lambda x: x["date"], reverse=True)
        return dates
    
    def _date_info(self, date_str: str, data: dict) -> dict:
        """Extract date info from queue data."""
        return {
            "date": date_str,
            "topic": data.get("topic", ""),
            "total_count": data.get("total_count", 0),
            "pending_count": sum(1 for c in data.get("candidates", []) if c.get("status") == "pending"),
            "approved_count": sum(1 for c in data.get("candidates", []) if c.get("status") == "approved"),
        }


# Global queue storage instance
_queue_storage = None


def get_queue_storage() -> QueueStorage:
    """Get the global queue storage instance."""
    global _queue_storage
    if _queue_storage is None:
        _queue_storage = QueueStorage()
    return _queue_storage
