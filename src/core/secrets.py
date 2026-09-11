"""
Secret loading helpers.

Runtime priority:
1. AWS Secrets Manager JSON secret, when BLUEGRASS_SECRET_ARN or APP_SECRET_ARN is set.
2. Existing environment variables / .env values.

Terraform should track the secret container, not the secret value.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Iterable


DEFAULT_SECRET_ARN_ENVS = ("BLUEGRASS_SECRET_ARN", "APP_SECRET_ARN", "KLING_SECRET_ARN")


@lru_cache(maxsize=8)
def _load_secret_json(secret_id: str, region_name: str) -> dict:
    import boto3

    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString") or "{}"
    data = json.loads(secret_string)
    if not isinstance(data, dict):
        raise ValueError("Secrets Manager value must be a JSON object.")
    return data


def _first_env(names: Iterable[str]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def get_secret_value(
    env_name: str,
    secret_keys: Iterable[str] | None = None,
    *,
    default: str = "",
    secret_arn_envs: Iterable[str] = DEFAULT_SECRET_ARN_ENVS,
) -> str:
    """
    Read a credential from AWS Secrets Manager first, then env vars.

    Args:
        env_name: Environment variable fallback name.
        secret_keys: JSON keys to try inside the AWS secret. Defaults to env_name.
        default: Returned when neither AWS nor env has a value.
        secret_arn_envs: Env vars that may contain the Secrets Manager ARN/name.
    """
    secret_id = _first_env(secret_arn_envs)
    keys = list(secret_keys or (env_name,))

    if secret_id:
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        try:
            data = _load_secret_json(secret_id, region)
            for key in keys:
                value = data.get(key)
                if value:
                    return str(value)
        except Exception:
            # Local development should keep working with .env fallback.
            pass

    return os.getenv(env_name, default)
