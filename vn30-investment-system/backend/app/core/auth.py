"""Verify Vnstock access without persisting credentials or importing its SDK."""

from datetime import UTC, datetime
from typing import Literal

import requests
from pydantic import BaseModel, Field

VERIFY_URL = "https://vnstocks.com/api/vnstock/license/verify"
KNOWN_TIERS = {"guest", "free", "community", "bronze", "silver", "gold", "golden", "diamond"}


class AccessStatus(BaseModel):
    """Safe account status: deliberately excludes key, account details and raw errors."""

    status: Literal["VERIFIED", "MISSING_KEY", "REJECTED", "UNAVAILABLE"]
    tier: str | None = None
    http_status: int | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None


def verify_access(api_key: str | None, timeout_seconds: float = 20) -> AccessStatus:
    """Send key in Authorization header only; errors never include request objects."""
    if not api_key or not api_key.strip():
        return AccessStatus(status="MISSING_KEY", reason="API_KEY_NOT_CONFIGURED")
    try:
        response = requests.get(
            VERIFY_URL,
            params={"device_id": "vibe-setup"},
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout_seconds,
            allow_redirects=False,
        )
        if response.status_code in (401, 403):
            return AccessStatus(
                status="REJECTED", http_status=response.status_code, reason="API_KEY_REJECTED"
            )
        if response.status_code != 200:
            return AccessStatus(
                status="UNAVAILABLE",
                http_status=response.status_code,
                reason="SERVER_DID_NOT_VERIFY_ACCESS",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            return AccessStatus(
                status="UNAVAILABLE", http_status=200, reason="UNEXPECTED_RESPONSE_SCHEMA"
            )
        if payload.get("valid") is False or payload.get("success") is False or payload.get("error"):
            return AccessStatus(status="REJECTED", http_status=200, reason="ACCESS_NOT_VALID")
        subscription = payload.get("subscription")
        tier = subscription.get("tier") if isinstance(subscription, dict) else None
        # A free plan may be active with subscription=null. Require explicit userType;
        # null alone is not evidence of a free account.
        user_type = payload.get("userType")
        if (
            subscription is None
            and isinstance(payload.get("hasActiveSubscription"), bool)
            and isinstance(user_type, str)
            and user_type.strip().lower() in {"free", "community"}
        ):
            tier = user_type.strip().lower()
        if not isinstance(tier, str) or tier.strip().lower() not in KNOWN_TIERS:
            return AccessStatus(status="UNAVAILABLE", http_status=200, reason="TIER_NOT_CONFIRMED")
        if payload.get("hasActiveSubscription") is False and tier.strip().lower() not in {
            "free",
            "community",
            "guest",
        }:
            return AccessStatus(
                status="REJECTED", http_status=200, reason="PAID_SUBSCRIPTION_INACTIVE"
            )
        return AccessStatus(status="VERIFIED", tier=tier.strip().lower(), http_status=200)
    except (requests.RequestException, ValueError):
        return AccessStatus(status="UNAVAILABLE", reason="VERIFICATION_REQUEST_FAILED")
