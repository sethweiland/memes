"""
Shared S3 access and the canonical bucket layout.

Bucket (default): bluegrass-meme-pipeline-dev-meme-assets (us-east-1)

    public/memes/templates/{id}.{ext}              # existing catalog — do not rename
    public/memes/generated/{hash}_{stem}.jpg       # IG-ready JPEGs (MemeAssetUploader)

    ops/tenant.yaml                                # private operator tenant (not in git)
    ops/projects/board.json                        # private project board
    ops/calendar/snapshot.json                     # private calendar snapshot (no OAuth)
    ops/spend/tech_spend.json                      # private operator spend ledger (not in git)
    ops/queue/daily-candidates/{YYYY-MM-DD}.json   # private daily queue
    ops/queue/x-activity/{YYYY-MM-DD}.json         # private X drafts (Stevie)
    ops/grok-bot/routines.json                     # private Grok Bot routine catalog
    ops/usage/{provider}/{YYYY}/{MM}.json          # private monthly token usage

Public GET is ONLY ``public/memes/*`` (Terraform bucket policy). Queue and usage
JSON are ops data and must never be written under ``public/``.

Legacy read-only fallbacks (not written by current code):

    queue/daily-candidates/{date}.json             # PR #7 path
    data/token_usage.jsonl                         # local-only token log
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from src.core.secrets import get_secret_value


logger = logging.getLogger(__name__)

ObjectKind = Literal["public_meme", "private_ops"]


class BucketLayout:
    """Canonical prefixes. Keep IAM, docs, and writers aligned with these."""

    PUBLIC_PREFIX = "public/memes/"
    TEMPLATES_PREFIX = "public/memes/templates/"
    GENERATED_PREFIX = "public/memes/generated/"
    OPS_PREFIX = "ops/"
    QUEUE_PREFIX = "ops/queue/daily-candidates/"
    QUEUE_LEGACY_PREFIX = "queue/daily-candidates/"
    X_ACTIVITY_PREFIX = "ops/queue/x-activity/"
    PROJECTS_PREFIX = "ops/projects/"
    PROJECTS_BOARD_KEY = "ops/projects/board.json"
    CALENDAR_PREFIX = "ops/calendar/"
    CALENDAR_SNAPSHOT_KEY = "ops/calendar/snapshot.json"
    GROK_BOT_PREFIX = "ops/grok-bot/"
    GROK_BOT_ROUTINES_KEY = "ops/grok-bot/routines.json"
    TENANT_KEY = "ops/tenant.yaml"
    SPEND_PREFIX = "ops/spend/"
    TECH_SPEND_KEY = "ops/spend/tech_spend.json"
    USAGE_PREFIX = "ops/usage/"

    @staticmethod
    def normalize_prefix(prefix: str) -> str:
        prefix = (prefix or "").strip().lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return prefix

    @staticmethod
    def safe_provider(provider: str) -> str:
        cleaned = "".join(
            ch for ch in (provider or "").lower() if ch.isalnum() or ch in "-_"
        )
        if not cleaned:
            raise ValueError("provider must contain letters or digits")
        return cleaned

    @classmethod
    def queue_key(cls, date_str: str) -> str:
        return f"{cls.QUEUE_PREFIX}{date_str}.json"

    @classmethod
    def queue_legacy_key(cls, date_str: str) -> str:
        return f"{cls.QUEUE_LEGACY_PREFIX}{date_str}.json"

    @classmethod
    def x_activity_key(cls, date_str: str) -> str:
        return f"{cls.X_ACTIVITY_PREFIX}{date_str}.json"

    @classmethod
    def grok_bot_routines_key(cls) -> str:
        return cls.GROK_BOT_ROUTINES_KEY

    @classmethod
    def projects_board_key(cls) -> str:
        return cls.PROJECTS_BOARD_KEY

    @classmethod
    def calendar_snapshot_key(cls) -> str:
        return cls.CALENDAR_SNAPSHOT_KEY

    @classmethod
    def tenant_key(cls) -> str:
        return cls.TENANT_KEY

    @classmethod
    def tech_spend_key(cls) -> str:
        return cls.TECH_SPEND_KEY

    @classmethod
    def usage_key(cls, provider: str, year: int, month: int) -> str:
        return f"{cls.USAGE_PREFIX}{cls.safe_provider(provider)}/{year:04d}/{month:02d}.json"

    @classmethod
    def require_public_meme_key(cls, key: str) -> str:
        if not key.startswith(cls.PUBLIC_PREFIX):
            raise ValueError(
                f"public meme objects must live under {cls.PUBLIC_PREFIX}: {key}"
            )
        return key

    @classmethod
    def require_ops_key(cls, key: str) -> str:
        if key.startswith(cls.PUBLIC_PREFIX):
            raise ValueError(f"ops data must never be written under public/: {key}")
        if not key.startswith(cls.OPS_PREFIX) and not key.startswith(
            cls.QUEUE_LEGACY_PREFIX
        ):
            raise ValueError(
                f"ops objects must live under {cls.OPS_PREFIX} "
                f"(or legacy {cls.QUEUE_LEGACY_PREFIX}): {key}"
            )
        return key


class PreconditionFailed(Exception):
    """S3 conditional write (If-Match / If-None-Match) was rejected."""


@dataclass
class ObjectResult:
    body: bytes
    etag: Optional[str]
    key: str


def _normalize_etag(etag: Optional[str]) -> Optional[str]:
    if not etag:
        return None
    return etag.strip()


class S3Store:
    """
    One boto3 client + key-safety checks for every S3 read/write in this repo.

    Configuration (env or AWS Secrets Manager):
    - MEME_ASSETS_BUCKET
    - MEME_ASSETS_PUBLIC_BASE_URL
    - AWS_DEFAULT_REGION / AWS_REGION (default us-east-1)
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        public_base_url: Optional[str] = None,
    ):
        self.bucket = (
            bucket
            or get_secret_value(
                "MEME_ASSETS_BUCKET",
                secret_keys=["MEME_ASSETS_BUCKET", "AWS_S3_BUCKET"],
            )
            or ""
        ).strip()
        self.region = (
            region
            or get_secret_value(
                "AWS_DEFAULT_REGION",
                secret_keys=["AWS_DEFAULT_REGION", "AWS_REGION"],
                default="us-east-1",
            )
            or "us-east-1"
        )
        self.public_base_url = (
            public_base_url
            or get_secret_value(
                "MEME_ASSETS_PUBLIC_BASE_URL",
                secret_keys=["MEME_ASSETS_PUBLIC_BASE_URL"],
            )
            or ""
        ).strip()
        if self.bucket and not self.public_base_url:
            self.public_base_url = f"https://{self.bucket}.s3.amazonaws.com"
        self._client = None

    @classmethod
    def from_env(cls) -> "S3Store":
        return cls()

    @property
    def configured(self) -> bool:
        return bool(self.bucket)

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def public_url(self, key: str) -> str:
        BucketLayout.require_public_meme_key(key)
        return f"{self.public_base_url.rstrip('/')}/{key}"

    def get_object(self, key: str) -> Optional[ObjectResult]:
        if not self.configured:
            return None
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _is_missing(exc):
                return None
            raise
        return ObjectResult(
            body=response["Body"].read(),
            etag=_normalize_etag(response.get("ETag")),
            key=key,
        )

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        kind: ObjectKind,
        content_type: str,
        cache_control: Optional[str] = None,
        if_match: Optional[str] = None,
        if_none_match: Optional[str] = None,
    ) -> str:
        if not self.configured:
            raise RuntimeError("S3 is not configured (MEME_ASSETS_BUCKET is empty)")
        if kind == "public_meme":
            BucketLayout.require_public_meme_key(key)
        elif kind == "private_ops":
            BucketLayout.require_ops_key(key)
        else:
            raise ValueError(f"unknown object kind: {kind}")

        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if cache_control:
            kwargs["CacheControl"] = cache_control
        if if_match:
            kwargs["IfMatch"] = if_match.strip('"')
        if if_none_match:
            kwargs["IfNoneMatch"] = if_none_match

        try:
            response = self._put(kwargs)
        except TypeError:
            # Older botocore without IfMatch / IfNoneMatch on put_object.
            kwargs.pop("IfMatch", None)
            kwargs.pop("IfNoneMatch", None)
            logger.warning(
                "boto3 put_object does not support conditional writes; writing %s unconditionally",
                key,
            )
            response = self._put(kwargs)
        except Exception as exc:
            if _is_precondition_failed(exc):
                raise PreconditionFailed(str(exc)) from exc
            # ParamValidationError if IfMatch is unknown
            if _is_unknown_conditional_param(exc) and (
                "IfMatch" in kwargs or "IfNoneMatch" in kwargs
            ):
                kwargs.pop("IfMatch", None)
                kwargs.pop("IfNoneMatch", None)
                logger.warning(
                    "boto3 rejected conditional PutObject params; writing %s unconditionally",
                    key,
                )
                response = self._put(kwargs)
            else:
                raise
        return _normalize_etag(response.get("ETag")) or ""

    def _put(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return self.client.put_object(**kwargs)

    def get_json(self, key: str) -> Optional[tuple[Any, Optional[str]]]:
        result = self.get_object(key)
        if result is None:
            return None
        return json.loads(result.body.decode("utf-8")), result.etag

    def put_json(
        self,
        key: str,
        data: Any,
        *,
        kind: ObjectKind = "private_ops",
        if_match: Optional[str] = None,
        if_none_match: Optional[str] = None,
    ) -> str:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        return self.put_object(
            key,
            body,
            kind=kind,
            content_type="application/json",
            if_match=if_match,
            if_none_match=if_none_match,
        )

    def list_keys(self, prefix: str) -> list[str]:
        if not self.configured:
            return []
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if key:
                    keys.append(key)
        return keys


_store: Optional[S3Store] = None


def get_s3_store() -> S3Store:
    """Process-wide S3Store (lazy). Tests should call reset_s3_store()."""
    global _store
    if _store is None:
        _store = S3Store.from_env()
    return _store


def reset_s3_store() -> None:
    global _store
    _store = None


def _is_missing(exc: BaseException) -> bool:
    code = _error_code(exc)
    return code in {"NoSuchKey", "404", "NotFound"}


def _is_precondition_failed(exc: BaseException) -> bool:
    code = _error_code(exc)
    return code in {"PreconditionFailed", "412"}


def _is_unknown_conditional_param(exc: BaseException) -> bool:
    name = type(exc).__name__
    message = str(exc)
    return name == "ParamValidationError" or "IfMatch" in message or "IfNoneMatch" in message


def _error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error") or {}
        code = error.get("Code")
        if code:
            return str(code)
    return ""
