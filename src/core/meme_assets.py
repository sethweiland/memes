"""
S3 asset hosting for meme images.

Uploads memes to S3 with public HTTPS URLs for Instagram Graph API.
Automatically converts images to JPEG format if needed.

Generated JPEGs go under ``public/memes/generated/``. Queue JSON uses the
shared ``S3Store`` and lives under ``ops/queue/`` (see ``src/core/s3_store.py``).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from PIL import Image

from src.core.s3_store import BucketLayout, S3Store, get_s3_store
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
    - MEME_ASSETS_PUBLIC_PREFIX: Prefix for generated JPEGs
      (default: public/memes/generated/)
    - AWS_DEFAULT_REGION: AWS region (default: us-east-1)
    """
    
    def __init__(
        self,
        bucket: Optional[str] = None,
        public_base_url: Optional[str] = None,
        public_prefix: Optional[str] = None,
        region: Optional[str] = None,
        store: Optional[S3Store] = None,
    ):
        """
        Initialize uploader with optional config overrides.
        
        Args:
            bucket: S3 bucket name (defaults to MEME_ASSETS_BUCKET env)
            public_base_url: Base HTTPS URL (defaults to MEME_ASSETS_PUBLIC_BASE_URL env)
            public_prefix: Object key prefix (defaults to MEME_ASSETS_PUBLIC_PREFIX env)
            region: AWS region (defaults to AWS_DEFAULT_REGION env)
            store: Shared S3Store (defaults to env-configured store)
        """
        self.store = store or S3Store(
            bucket=bucket,
            region=region,
            public_base_url=public_base_url,
        )
        self.bucket = self.store.bucket
        self.public_base_url = self.store.public_base_url
        self.region = self.store.region

        configured_prefix = public_prefix or get_secret_value(
            "MEME_ASSETS_PUBLIC_PREFIX",
            secret_keys=["MEME_ASSETS_PUBLIC_PREFIX"],
            default="",
        )
        self.public_prefix = BucketLayout.normalize_prefix(
            configured_prefix or BucketLayout.GENERATED_PREFIX
        )
        if not self.public_prefix.startswith(BucketLayout.PUBLIC_PREFIX):
            raise ValueError(
                "MEME_ASSETS_PUBLIC_PREFIX must stay under "
                f"{BucketLayout.PUBLIC_PREFIX} (got {self.public_prefix!r})"
            )

        if not self.store.configured:
            raise ValueError(
                "MEME_ASSETS_BUCKET is required. "
                "Set it in .env or AWS Secrets Manager. "
                "See infra/meme-assets/README.md for setup."
            )
    
    @property
    def s3_client(self):
        """Shared boto3 S3 client (via S3Store)."""
        return self.store.client
    
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
            self.store.put_object(
                s3_key,
                jpeg_bytes,
                kind="public_meme",
                content_type="image/jpeg",
                cache_control="public, max-age=31536000",  # 1 year cache
            )
            
            # Generate public URL
            public_url = self.store.public_url(s3_key)
            
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
    
    Writes ``ops/queue/daily-candidates/{date}.json`` (private). Reads the same
    key first, then the PR #7 legacy prefix ``queue/daily-candidates/``, then
    the local cache.
    """
    
    def __init__(
        self,
        bucket: Optional[str] = None,
        queue_prefix: str = BucketLayout.QUEUE_PREFIX,
        local_dir: Optional[Path] = None,
        store: Optional[S3Store] = None,
    ):
        """
        Initialize queue storage.
        
        Args:
            bucket: S3 bucket name (defaults to MEME_ASSETS_BUCKET env)
            queue_prefix: S3 prefix for new writes (default: ops/queue/daily-candidates/)
            local_dir: Local directory for cache/fallback (default: data/daily_candidates)
            store: Shared S3Store (defaults to env-configured store)
        """
        self.store = store or S3Store(bucket=bucket)
        self.bucket = self.store.bucket
        self.queue_prefix = BucketLayout.normalize_prefix(
            queue_prefix or BucketLayout.QUEUE_PREFIX
        )
        self.legacy_prefix = BucketLayout.QUEUE_LEGACY_PREFIX
        self.local_dir = local_dir or Path("data/daily_candidates")
        self.region = self.store.region
    
    @property
    def s3_client(self):
        """Shared boto3 S3 client (via S3Store)."""
        return self.store.client
    
    def _s3_key(self, date_str: str) -> str:
        """Canonical S3 key for a queue file."""
        if self.queue_prefix == BucketLayout.QUEUE_PREFIX:
            return BucketLayout.queue_key(date_str)
        return f"{self.queue_prefix}{date_str}.json"
    
    def _legacy_key(self, date_str: str) -> str:
        return BucketLayout.queue_legacy_key(date_str)
    
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
        
        if not self.store.configured:
            logger.warning("S3 bucket not configured, queue saved locally only")
            return False
        
        try:
            s3_key = self._s3_key(date_str)
            self.store.put_object(
                s3_key,
                json_bytes,
                kind="private_ops",
                content_type="application/json",
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
        if self.store.configured:
            keys = [self._s3_key(date_str)]
            if self._legacy_key(date_str) not in keys:
                keys.append(self._legacy_key(date_str))
            for s3_key in keys:
                try:
                    result = self.store.get_json(s3_key)
                    if result:
                        data, _etag = result
                        logger.info(f"Loaded queue from S3: s3://{self.bucket}/{s3_key}")
                        return data
                except Exception as e:
                    logger.warning(f"Failed to load queue from S3 ({s3_key}): {e}")
        
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
        
        if self.store.configured:
            prefixes = [self.queue_prefix]
            if self.legacy_prefix not in prefixes:
                prefixes.append(self.legacy_prefix)
            try:
                for prefix in prefixes:
                    for key in self.store.list_keys(prefix):
                        if not key.endswith(".json"):
                            continue
                        date_str = key[len(prefix):].removeprefix("/").replace(".json", "")
                        if date_str and date_str not in dates_map:
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
        _queue_storage = QueueStorage(store=get_s3_store())
    return _queue_storage


def reset_queue_storage(queue: QueueStorage | None = None) -> None:
    """Clear or replace the process-wide QueueStorage (tests)."""
    global _queue_storage
    _queue_storage = queue
