"""
Instagram Graph API publisher for approved memes.

Human-in-the-loop workflow:
1. User approves a meme (image + caption) in the web UI
2. POST to /{ig-user-id}/media with image_url + caption (create container)
3. Poll container status until FINISHED
4. POST to /{ig-user-id}/media_publish with creation_id

Requires:
- META_IG_ACCESS_TOKEN (from env / AWS Secrets Manager)
- META_IG_USER_ID (default 17841449649203293)
- A publicly reachable JPEG URL for the image

Multi-brand support:
- Optional instagram_brands.json file for managing multiple Instagram accounts
- Each brand has its own ig_user_id, page_id, app_id, and access_token_env
- Specify brand when publishing: publish_to_instagram(..., brand="mybrand")

See: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/content-publishing
"""

from __future__ import annotations

import time
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal
import requests

from src.core.secrets import get_secret_value


logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_IG_USER_ID = "17841449649203293"  # @memes851988
DEFAULT_META_APP_ID = "1042489268787325"  # Bluegrass Memes Publisher
DEFAULT_PAGE_ID = "1370368009487261"      # High Lonesome Memes

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


@dataclass
class InstagramPublishResult:
    """Result of an Instagram publish operation."""
    success: bool
    post_id: Optional[str] = None
    permalink: Optional[str] = None
    error: Optional[str] = None
    container_id: Optional[str] = None


@dataclass
class InstagramConfig:
    """Configuration for Instagram publishing (multi-brand support)."""
    ig_user_id: str
    access_token: str
    app_id: str = DEFAULT_META_APP_ID
    page_id: str = DEFAULT_PAGE_ID
    brand_name: str = "default"


class InstagramPublisher:
    """
    Publish approved memes to Instagram via Meta Graph API.
    
    Workflow:
    1. create_container() - Upload image + caption, get container ID
    2. poll_container() - Wait until container status is FINISHED
    3. publish_container() - Publish the container to Instagram
    """
    
    def __init__(self, config: Optional[InstagramConfig] = None):
        """
        Initialize publisher with optional config override.
        
        Args:
            config: Optional brand-specific config. If None, loads from env/secrets.
        """
        if config:
            self.config = config
        else:
            self.config = self._load_default_config()
    
    @staticmethod
    def _load_default_config() -> InstagramConfig:
        """Load default Instagram configuration from environment or secrets."""
        access_token = get_secret_value(
            "META_IG_ACCESS_TOKEN",
            secret_keys=["META_IG_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN"],
        )
        
        if not access_token:
            raise ValueError(
                "META_IG_ACCESS_TOKEN is required. "
                "Set it in your .env file or AWS Secrets Manager."
            )
        
        ig_user_id = get_secret_value(
            "META_IG_USER_ID",
            secret_keys=["META_IG_USER_ID", "INSTAGRAM_USER_ID"],
            default=DEFAULT_IG_USER_ID,
        )
        
        page_id = get_secret_value(
            "META_PAGE_ID",
            secret_keys=["META_PAGE_ID", "FACEBOOK_PAGE_ID"],
            default=DEFAULT_PAGE_ID,
        )
        
        app_id = get_secret_value(
            "META_APP_ID",
            secret_keys=["META_APP_ID"],
            default=DEFAULT_META_APP_ID,
        )
        
        return InstagramConfig(
            ig_user_id=ig_user_id,
            access_token=access_token,
            app_id=app_id,
            page_id=page_id,
        )
    
    def create_container(
        self,
        image_url: str,
        caption: str,
        media_type: Literal["IMAGE", "VIDEO", "CAROUSEL_ALBUM"] = "IMAGE",
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Create an Instagram media container.
        
        Args:
            image_url: Publicly accessible JPEG URL (required by Instagram Graph API)
            caption: Caption text for the post
            media_type: Type of media (IMAGE, VIDEO, CAROUSEL_ALBUM)
        
        Returns:
            (success: bool, container_id: Optional[str], error: Optional[str])
        """
        endpoint = f"{GRAPH_API_BASE}/{self.config.ig_user_id}/media"
        
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": self.config.access_token,
        }
        
        if media_type != "IMAGE":
            payload["media_type"] = media_type
        
        try:
            logger.info(f"Creating Instagram container: {image_url[:100]}...")
            response = requests.post(endpoint, data=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            container_id = data.get("id")
            
            if container_id:
                logger.info(f"Container created: {container_id}")
                return True, container_id, None
            else:
                error = f"No container ID in response: {data}"
                logger.error(error)
                return False, None, error
                
        except requests.exceptions.RequestException as e:
            error = f"Failed to create container: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error = f"Instagram API error: {error_data.get('error', {}).get('message', str(e))}"
                except Exception:
                    error = f"Instagram API error: {e.response.text[:200]}"
            logger.error(error)
            return False, None, error
    
    def check_container_status(
        self,
        container_id: str,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Check the status of a media container.
        
        Args:
            container_id: The container ID to check
        
        Returns:
            (status: Optional[str], error: Optional[str])
            Status can be: IN_PROGRESS, FINISHED, ERROR, EXPIRED
        """
        endpoint = f"{GRAPH_API_BASE}/{container_id}"
        params = {
            "fields": "status_code",
            "access_token": self.config.access_token,
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            status = data.get("status_code")
            return status, None
            
        except requests.exceptions.RequestException as e:
            error = f"Failed to check container status: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error = f"Instagram API error: {error_data.get('error', {}).get('message', str(e))}"
                except Exception:
                    error = f"Instagram API error: {e.response.text[:200]}"
            logger.error(error)
            return None, error
    
    def poll_container(
        self,
        container_id: str,
        max_wait: int = 120,
        poll_interval: int = 3,
    ) -> tuple[bool, Optional[str]]:
        """
        Poll container status until FINISHED or error.
        
        Args:
            container_id: The container ID to poll
            max_wait: Maximum seconds to wait
            poll_interval: Seconds between status checks
        
        Returns:
            (success: bool, error: Optional[str])
        """
        elapsed = 0
        
        while elapsed < max_wait:
            status, error = self.check_container_status(container_id)
            
            if error:
                return False, error
            
            if status == "FINISHED":
                logger.info(f"Container {container_id} is ready")
                return True, None
            elif status == "ERROR":
                return False, "Container processing failed"
            elif status == "EXPIRED":
                return False, "Container expired before publishing"
            
            logger.debug(f"Container {container_id} status: {status}, waiting...")
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        return False, f"Timeout waiting for container (max {max_wait}s)"
    
    def publish_container(
        self,
        container_id: str,
    ) -> tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Publish a ready container to Instagram.
        
        Args:
            container_id: The container ID to publish
        
        Returns:
            (success: bool, post_id: Optional[str], permalink: Optional[str], error: Optional[str])
        """
        endpoint = f"{GRAPH_API_BASE}/{self.config.ig_user_id}/media_publish"
        
        payload = {
            "creation_id": container_id,
            "access_token": self.config.access_token,
        }
        
        try:
            logger.info(f"Publishing container {container_id}...")
            response = requests.post(endpoint, data=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            post_id = data.get("id")
            
            if post_id:
                logger.info(f"Published to Instagram: {post_id}")
                # Get permalink
                permalink = self._get_permalink(post_id)
                return True, post_id, permalink, None
            else:
                error = f"No post ID in response: {data}"
                logger.error(error)
                return False, None, None, error
                
        except requests.exceptions.RequestException as e:
            error = f"Failed to publish container: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error = f"Instagram API error: {error_data.get('error', {}).get('message', str(e))}"
                except Exception:
                    error = f"Instagram API error: {e.response.text[:200]}"
            logger.error(error)
            return False, None, None, error
    
    def _get_permalink(self, post_id: str) -> Optional[str]:
        """Get the permalink URL for a published post."""
        endpoint = f"{GRAPH_API_BASE}/{post_id}"
        params = {
            "fields": "permalink",
            "access_token": self.config.access_token,
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("permalink")
        except Exception as e:
            logger.warning(f"Failed to get permalink: {e}")
            return None
    
    def publish(
        self,
        image_url: str,
        caption: str,
        max_wait: int = 120,
    ) -> InstagramPublishResult:
        """
        Complete publish workflow: create container → poll → publish.
        
        Args:
            image_url: Publicly accessible JPEG URL
            caption: Caption text
            max_wait: Maximum seconds to wait for container processing
        
        Returns:
            InstagramPublishResult with success status and details
        """
        # Step 1: Create container
        success, container_id, error = self.create_container(image_url, caption)
        if not success or not container_id:
            return InstagramPublishResult(
                success=False,
                error=error or "Failed to create container",
            )
        
        # Step 2: Poll until ready
        success, error = self.poll_container(container_id, max_wait=max_wait)
        if not success:
            return InstagramPublishResult(
                success=False,
                container_id=container_id,
                error=error or "Container processing failed",
            )
        
        # Step 3: Publish
        success, post_id, permalink, error = self.publish_container(container_id)
        
        return InstagramPublishResult(
            success=success,
            post_id=post_id,
            permalink=permalink,
            error=error,
            container_id=container_id,
        )


def load_brand_config(brand_name: str = "default") -> Optional[InstagramConfig]:
    """
    Load brand configuration from instagram_brands.json if it exists.
    
    Args:
        brand_name: Name of the brand to load (default: "default")
    
    Returns:
        InstagramConfig or None if file doesn't exist or brand not found
    """
    config_path = Path("instagram_brands.json")
    if not config_path.exists():
        return None
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        brands = data.get("brands", {})
        brand_data = brands.get(brand_name)
        
        if not brand_data:
            logger.warning(f"Brand '{brand_name}' not found in instagram_brands.json")
            return None
        
        # Get access token from the specified env variable
        access_token_env = brand_data.get("access_token_env", "META_IG_ACCESS_TOKEN")
        access_token = get_secret_value(access_token_env)
        
        if not access_token:
            logger.warning(f"Access token not found for env var: {access_token_env}")
            return None
        
        return InstagramConfig(
            ig_user_id=brand_data.get("ig_user_id", DEFAULT_IG_USER_ID),
            access_token=access_token,
            app_id=brand_data.get("app_id", DEFAULT_META_APP_ID),
            page_id=brand_data.get("page_id", DEFAULT_PAGE_ID),
            brand_name=brand_name,
        )
    except Exception as e:
        logger.error(f"Failed to load brand config: {e}")
        return None


def publish_to_instagram(
    image_url: str,
    caption: str,
    config: Optional[InstagramConfig] = None,
    brand: str = "default",
) -> InstagramPublishResult:
    """
    Convenience function to publish a meme to Instagram.
    
    Args:
        image_url: Publicly accessible JPEG URL (required by Instagram Graph API)
        caption: Caption text for the post
        config: Optional brand-specific config (overrides brand parameter)
        brand: Brand name to load from instagram_brands.json (default: "default")
    
    Returns:
        InstagramPublishResult with success status and details
    
    Example:
        >>> result = publish_to_instagram(
        ...     image_url="https://example.com/meme.jpg",
        ...     caption="This is a meme! #memes #funny"
        ... )
        >>> if result.success:
        ...     print(f"Published: {result.permalink}")
        ... else:
        ...     print(f"Error: {result.error}")
        
        # Multi-brand example:
        >>> result = publish_to_instagram(
        ...     image_url="https://example.com/meme.jpg",
        ...     caption="Another meme!",
        ...     brand="mybrand"
        ... )
    """
    # If no config provided, try to load from brand config file
    if config is None and brand != "default":
        config = load_brand_config(brand)
    
    publisher = InstagramPublisher(config)
    return publisher.publish(image_url, caption)
