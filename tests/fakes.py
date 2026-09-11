"""In-memory S3 stand-in for unit tests."""

from __future__ import annotations

import tests.bootstrap  # noqa: F401 — namespace packages before src imports

import json
import uuid
from typing import Any, Optional

from src.core.s3_store import BucketLayout, ObjectResult, PreconditionFailed


class MemoryS3Store:
    bucket = "test-bucket"
    region = "us-east-1"
    public_base_url = "https://test-bucket.s3.amazonaws.com"

    def __init__(self, *, configured: bool = True):
        self.configured = configured
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls = 0
        self.fail_gets = False
        self.fail_puts = False

    def public_url(self, key: str) -> str:
        BucketLayout.require_public_meme_key(key)
        return f"{self.public_base_url}/{key}"

    def get_object(self, key: str) -> Optional[ObjectResult]:
        if self.fail_gets:
            raise RuntimeError("s3 get down")
        if key not in self.objects:
            return None
        body, etag = self.objects[key]
        return ObjectResult(body=body, etag=etag, key=key)

    def get_json(self, key: str) -> Optional[tuple[Any, Optional[str]]]:
        result = self.get_object(key)
        if result is None:
            return None
        return json.loads(result.body.decode("utf-8")), result.etag

    def put_object(
        self,
        key: str,
        body: bytes,
        *,
        kind: str,
        content_type: str,
        cache_control: Optional[str] = None,
        if_match: Optional[str] = None,
        if_none_match: Optional[str] = None,
    ) -> str:
        if self.fail_puts:
            raise RuntimeError("s3 put down")
        if kind == "public_meme":
            BucketLayout.require_public_meme_key(key)
        elif kind == "private_ops":
            BucketLayout.require_ops_key(key)
        else:
            raise ValueError(kind)
        existing = self.objects.get(key)
        if if_none_match == "*" and existing is not None:
            raise PreconditionFailed("object exists")
        if if_match:
            if existing is None or existing[1].strip('"') != if_match.strip('"'):
                raise PreconditionFailed("etag mismatch")
        etag = f'"{uuid.uuid4().hex}"'
        self.objects[key] = (body, etag)
        self.put_calls += 1
        return etag

    def put_json(
        self,
        key: str,
        data: Any,
        *,
        kind: str = "private_ops",
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
        if self.fail_gets:
            raise RuntimeError("s3 list down")
        return sorted(key for key in self.objects if key.startswith(prefix))
