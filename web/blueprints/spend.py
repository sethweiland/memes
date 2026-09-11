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


def _calculate_monthly_total(subscriptions: List[Dict], aws_live: Optional[Dict] = None) -> float:
    """Calculate estimated monthly total from active subscriptions."""
    total = 0.0
    
    for sub in subscriptions:
        if sub.get('status') != 'active':
            continue
            
        amount = sub.get('amount_usd', 0)
        cadence = sub.get('cadence', 'monthly')
        
        # Skip AWS from config if we have live data
        if aws_live and sub.get('id') == 'aws':
            continue
        
        # Convert to monthly equivalent
        if cadence == 'monthly':
            total += amount
        elif cadence == 'yearly':
            total += amount / 12
        elif cadence == 'usage':
            total += amount  # Already monthly estimate
    
    # Add live AWS if available
    if aws_live and not aws_live.get('error'):
        total += aws_live.get('amount', 0)
    
    return round(total, 2)


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
    
    # Try to get live AWS data
    aws_live = _get_aws_current_month_cost()
    
    # Calculate totals and counts
    monthly_total = _calculate_monthly_total(subscriptions, aws_live)
    status_counts = _count_by_status(subscriptions, cancelled)
    
    # Organize items by category
    subscription_items = [s for s in subscriptions if s.get('category') == 'subscription']
    usage_items = [s for s in subscriptions if s.get('category') == 'usage']
    
    return render_template(
        "spend/index.html",
        subscriptions=subscription_items,
        usage_items=usage_items,
        cancelled=cancelled,
        monthly_total=monthly_total,
        status_counts=status_counts,
        aws_live=aws_live,
        last_updated=spend_data.get('last_updated'),
        note=spend_data.get('note'),
        active_page="spend"
    )
