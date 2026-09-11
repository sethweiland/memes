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

bp = Blueprint("spend", __name__)


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
    Get current month xAI token usage from local tracking.
    Returns dict with amount, tokens, and call_count, or None if no data.
    """
    try:
        from datetime import datetime
        from pathlib import Path
        import sys
        
        # Add project root to path for token_tracker import
        project_root = Path(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from src.core.token_tracker import get_month_usage
        
        now = datetime.now()
        usage = get_month_usage("xai", now.year, now.month)
        
        if usage['call_count'] == 0:
            return None
        
        # Estimate cost: rough approximation based on grok-4.6 pricing
        # Real pricing varies by model, but this gives ballpark
        # grok-4.6: ~$0.015/1M input tokens, ~$0.075/1M output tokens (example rates)
        estimated_cost = usage.get('total_cost_usd', 0.0)
        if estimated_cost == 0 and usage['total_tokens'] > 0:
            # Rough estimate if not tracked: assume 50/50 split, use average rate
            estimated_cost = (usage['total_tokens'] / 1_000_000) * 0.045
        
        return {
            'amount': round(estimated_cost, 2),
            'tokens': usage['total_tokens'],
            'calls': usage['call_count'],
            'source': 'local_log',
            'period': f"{now.year}-{now.month:02d}"
        }
    except Exception as e:
        return {
            'error': str(e),
            'source': 'local_log_failed'
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
    fixed_items = [s for s in subscriptions if s.get('category') == 'fixed']
    variable_items = [s for s in subscriptions if s.get('category') == 'variable']
    
    return render_template(
        "spend/index.html",
        fixed_items=fixed_items,
        variable_items=variable_items,
        cancelled=cancelled,
        totals=totals,
        status_counts=status_counts,
        aws_live=aws_live,
        xai_usage=xai_usage,
        last_updated=spend_data.get('last_updated'),
        note=spend_data.get('note'),
        active_page="spend"
    )
