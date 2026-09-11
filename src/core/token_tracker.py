"""
Token usage tracking for cost monitoring.
Logs API calls to data/token_usage.jsonl for spend analysis.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


TOKEN_LOG_PATH = Path("data/token_usage.jsonl")


def log_token_usage(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: Optional[float] = None,
):
    """
    Log token usage to data/token_usage.jsonl.
    
    Args:
        provider: API provider (e.g., "xai", "openai")
        model: Model name
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        estimated_cost_usd: Estimated cost if known
    """
    TOKEN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_cost_usd": estimated_cost_usd,
    }
    
    with open(TOKEN_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_month_usage(provider: str, year: int, month: int) -> dict:
    """
    Get token usage totals for a specific month.
    
    Args:
        provider: Filter by provider (e.g., "xai", "openai")
        year: Year (e.g., 2026)
        month: Month (1-12)
    
    Returns:
        Dict with total_tokens, total_cost_usd, call_count
    """
    if not TOKEN_LOG_PATH.exists():
        return {"total_tokens": 0, "total_cost_usd": 0.0, "call_count": 0}
    
    total_tokens = 0
    total_cost = 0.0
    call_count = 0
    
    with open(TOKEN_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                
                # Parse timestamp
                timestamp = entry.get("timestamp", "")
                if not timestamp.startswith(f"{year:04d}-{month:02d}"):
                    continue
                
                # Filter by provider
                if entry.get("provider") != provider:
                    continue
                
                total_tokens += entry.get("total_tokens", 0)
                if entry.get("estimated_cost_usd"):
                    total_cost += entry["estimated_cost_usd"]
                call_count += 1
                
            except (json.JSONDecodeError, ValueError):
                continue
    
    return {
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "call_count": call_count,
    }
