"""
Spend blueprint - Tech spending tracker for ops/engineering costs.
Tracks subscriptions, API/usage costs, and provides live AWS data when available.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from flask import Blueprint, render_template

from src.core.projects import (
    SHARED_PROJECT,
    UNALLOCATED_PROJECT,
    build_project_rollup,
    format_project_label,
    project_meta,
    subscription_shares,
)

bp = Blueprint("spend", __name__)


def _annotate_items(items: List[Dict]) -> List[Dict]:
    annotated = []
    for item in items:
        row = dict(item)
        shares = subscription_shares(item)
        row["project_label"] = format_project_label(item)
        if UNALLOCATED_PROJECT in shares and (
            len(shares) == 1 or shares.get(UNALLOCATED_PROJECT, 0) >= 0.5
        ):
            row["project_tone"] = UNALLOCATED_PROJECT
        else:
            row["project_tone"] = max(shares, key=shares.get)
        annotated.append(row)
    return annotated


def _load_tech_spend() -> Dict[str, Any]:
    """Load tech spend data from data/tech_spend.json."""
    spend_path = Path("data/tech_spend.json")
    if not spend_path.exists():
        return {
            "subscriptions": [],
            "cancelled": [],
            "last_updated": None,
            "note": "No spend data found"
        }
    
    try:
        data = json.loads(spend_path.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        return {
            "subscriptions": [],
            "cancelled": [],
            "last_updated": None,
            "note": f"Error loading spend data: {e}"
        }


def _get_xai_token_usage() -> Optional[Dict[str, Any]]:
    """
    Get current month xAI token usage from the shared S3 monthly object
    (ops/usage/xai/{YYYY}/{MM}.json), with local fallback.
    """
    try:
        from src.core.token_tracker import HEURISTIC_USD_PER_MILLION_TOKENS, get_month_usage

        now = datetime.now()
        usage = get_month_usage("xai", now.year, now.month)

        if usage["call_count"] == 0:
            return None

        # Heuristic only — not xAI billing. See token_tracker.estimate_cost_usd.
        estimated_cost = usage.get("total_cost_usd", 0.0)
        if estimated_cost == 0 and usage["total_tokens"] > 0:
            estimated_cost = (usage["total_tokens"] / 1_000_000) * HEURISTIC_USD_PER_MILLION_TOKENS

        source = usage.get("source") or "local"
        by_project = usage.get("by_project") or {}
        project_parts = []
        for project_id, bucket in by_project.items():
            meta = project_meta(str(project_id))
            cost = round(float((bucket or {}).get("total_cost_usd") or 0), 2)
            calls = int((bucket or {}).get("call_count") or 0)
            pid = str(project_id)
            note = ""
            if pid == UNALLOCATED_PROJECT:
                note = "Missing project tag — shown on purpose."
            elif pid == SHARED_PROJECT:
                note = "Overhead that is not one product."
            project_parts.append(
                {
                    "id": pid,
                    "name": meta["name"],
                    "amount": cost,
                    "calls": calls,
                    "tokens": int((bucket or {}).get("total_tokens") or 0),
                    "note": note,
                }
            )
        project_parts.sort(key=lambda part: (-part["amount"], part["name"]))
        return {
            "amount": round(estimated_cost, 2),
            "tokens": usage["total_tokens"],
            "calls": usage["call_count"],
            "source": source,
            "period": f"{now.year}-{now.month:02d}",
            "by_project": by_project,
            "project_parts": project_parts,
            "legacy_untagged_xai_as_memes": int(
                usage.get("legacy_untagged_xai_as_memes") or 0
            ),
        }
    except Exception as e:
        return {
            "error": str(e),
            "source": "usage_read_failed",
        }


def _get_aws_current_month_cost() -> Optional[Dict[str, Any]]:
    """
    Fetch current month AWS cost from Cost Explorer API if credentials are available.
    Returns dict with amount and source, or None if unavailable/failed.
    """
    # Check if AWS credentials are present
    has_creds = bool(
        os.environ.get("AWS_ACCESS_KEY_ID") and 
        os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    
    if not has_creds:
        return None
    
    try:
        import boto3
        from datetime import date
        from dateutil.relativedelta import relativedelta
        
        # Get current month date range
        today = date.today()
        start_of_month = today.replace(day=1)
        end_of_month = (start_of_month + relativedelta(months=1)) - relativedelta(days=1)
        
        # Initialize Cost Explorer client
        ce_client = boto3.client('ce', region_name='us-east-1')
        
        # Get cost and usage
        response = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_of_month.strftime('%Y-%m-%d'),
                'End': (today + relativedelta(days=1)).strftime('%Y-%m-%d')  # CE API is exclusive end date
            },
            Granularity='MONTHLY',
            Metrics=['UnblendedCost']
        )
        
        if response.get('ResultsByTime'):
            amount = float(response['ResultsByTime'][0]['Total']['UnblendedCost']['Amount'])
            return {
                'amount': round(amount, 2),
                'source': 'live_api',
                'period': f"{start_of_month.strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}"
            }
    except ImportError:
        # boto3 or dateutil not available
        return None
    except Exception as e:
        # API call failed, return error info
        return {
            'error': str(e),
            'source': 'api_failed'
        }
    
    return None


def _calculate_totals(subscriptions: List[Dict], aws_live: Optional[Dict] = None, xai_usage: Optional[Dict] = None) -> Dict[str, float]:
    """Calculate fixed and variable monthly totals."""
    fixed_total = 0.0
    variable_total = 0.0
    
    for sub in subscriptions:
        # Include active and cancelling (still paying until cancelled)
        if sub.get('status') not in ('active', 'cancelling'):
            continue
            
        amount = sub.get('amount_usd', 0)
        cadence = sub.get('cadence', 'monthly')
        category = sub.get('category', 'fixed')
        
        # Skip AWS from config if we have live data
        if aws_live and sub.get('id') == 'aws':
            continue
        
        # Skip xAI tokens from config if we have usage data
        if xai_usage and sub.get('id') == 'xai-tokens':
            continue
        
        # Convert to monthly equivalent
        monthly_amount = 0
        if cadence == 'monthly':
            monthly_amount = amount
        elif cadence == 'yearly':
            monthly_amount = amount / 12
        elif cadence == 'usage':
            monthly_amount = amount
        
        # Add to appropriate category
        if category == 'variable':
            variable_total += monthly_amount
        else:
            fixed_total += monthly_amount
    
    # Add live AWS to variable if available
    if aws_live and not aws_live.get('error'):
        variable_total += aws_live.get('amount', 0)
    
    # Add xAI token usage to variable if available
    if xai_usage and not xai_usage.get('error'):
        variable_total += xai_usage.get('amount', 0)
    
    return {
        'fixed': round(fixed_total, 2),
        'variable': round(variable_total, 2),
        'total': round(fixed_total + variable_total, 2)
    }


def _count_by_status(subscriptions: List[Dict], cancelled: List[Dict]) -> Dict[str, int]:
    """Count subscriptions by status."""
    active = sum(1 for s in subscriptions if s.get('status') == 'active')
    cancelling = sum(1 for s in subscriptions if s.get('status') == 'cancelling')
    cancelled_count = len(cancelled)
    
    return {
        'active': active,
        'cancelling': cancelling,
        'cancelled': cancelled_count
    }


@bp.route("/")
def index():
    """Spend tracking dashboard."""
    # Load spend config
    spend_data = _load_tech_spend()
    subscriptions = spend_data.get('subscriptions', [])
    cancelled = spend_data.get('cancelled', [])
    
    # Try to get live data
    aws_live = _get_aws_current_month_cost()
    xai_usage = _get_xai_token_usage()
    
    # Calculate totals and counts
    totals = _calculate_totals(subscriptions, aws_live, xai_usage)
    status_counts = _count_by_status(subscriptions, cancelled)
    
    # Organize items by category
    fixed_items = _annotate_items(
        [s for s in subscriptions if s.get("category") == "fixed"]
    )
    variable_items = _annotate_items(
        [s for s in subscriptions if s.get("category") == "variable"]
    )
    cancelled_items = _annotate_items(cancelled)

    project_rollup = build_project_rollup(
        subscriptions, aws_live=aws_live, xai_usage=xai_usage
    )
    
    return render_template(
        "spend/index.html",
        fixed_items=fixed_items,
        variable_items=variable_items,
        cancelled=cancelled_items,
        totals=totals,
        status_counts=status_counts,
        aws_live=aws_live,
        xai_usage=xai_usage,
        project_rollup=project_rollup,
        last_updated=spend_data.get('last_updated'),
        note=spend_data.get('note'),
        active_page="spend",
        section="spend",
    )
