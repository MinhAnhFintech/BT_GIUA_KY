"""Credential fixtures are explicitly synthetic and never contact the license server."""

from unittest.mock import Mock, patch

import pytest
import requests

from backend.app.core.auth import VERIFY_URL, verify_access

TEST_KEY = "SYNTHETIC_TEST_ONLY_NOT_A_REAL_KEY"


@pytest.mark.parametrize("user_type", ["free", "community"])
@pytest.mark.parametrize("active", [False, True])
@patch("backend.app.core.auth.requests.get")
def test_explicit_community_account_with_null_subscription(
    get: Mock, active: bool, user_type: str
) -> None:
    get.return_value = Mock(
        status_code=200,
        json=lambda: {
            "deviceRegistered": True,
            "userType": user_type,
            "hasActiveSubscription": active,
            "subscription": None,
            "availablePackages": [],
        },
    )
    result = verify_access(TEST_KEY)
    assert result.status == "VERIFIED"
    assert result.tier == user_type


@patch("backend.app.core.auth.requests.get")
def test_expired_paid_subscription_is_rejected(get: Mock) -> None:
    get.return_value = Mock(
        status_code=200,
        json=lambda: {
            "subscription": {"tier": "silver"},
            "hasActiveSubscription": False,
        },
    )
    assert verify_access(TEST_KEY).status == "REJECTED"


@patch("backend.app.core.auth.requests.get")
def test_null_subscription_alone_does_not_imply_free_tier(get: Mock) -> None:
    get.return_value = Mock(status_code=200, json=lambda: {"subscription": None})
    assert verify_access(TEST_KEY).status == "UNAVAILABLE"


@patch("backend.app.core.auth.requests.get")
def test_key_is_header_only_and_never_in_status(get: Mock) -> None:
    get.return_value = Mock(status_code=200, json=lambda: {"subscription": {"tier": "silver"}})
    result = verify_access(TEST_KEY)
    assert result.status == "VERIFIED" and result.tier == "silver"
    assert TEST_KEY not in result.model_dump_json()
    args, kwargs = get.call_args
    assert args == (VERIFY_URL,)
    assert kwargs["headers"]["Authorization"] == f"Bearer {TEST_KEY}"
    assert TEST_KEY not in str(kwargs["params"])
    assert kwargs["allow_redirects"] is False


@patch("backend.app.core.auth.requests.get")
def test_missing_key_makes_no_request(get: Mock) -> None:
    assert verify_access(None).status == "MISSING_KEY"
    get.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    [
        (401, "REJECTED"),
        (403, "REJECTED"),
        (429, "UNAVAILABLE"),
        (500, "UNAVAILABLE"),
        (302, "UNAVAILABLE"),
    ],
)
@patch("backend.app.core.auth.requests.get")
def test_http_failure_never_becomes_community(get: Mock, code: int, status: str) -> None:
    get.return_value = Mock(status_code=code)
    result = verify_access(TEST_KEY)
    assert result.status == status
    assert result.tier is None


@pytest.mark.parametrize(
    "payload",
    [
        {"subscription": {"tier": "silver"}, "valid": False},
        {"subscription": {"tier": "silver"}, "success": False},
        {"error": TEST_KEY},
    ],
)
@patch("backend.app.core.auth.requests.get")
def test_invalid_response_never_succeeds(get: Mock, payload: dict) -> None:
    get.return_value = Mock(status_code=200, json=lambda: payload)
    result = verify_access(TEST_KEY)
    assert result.status == "REJECTED"
    assert TEST_KEY not in result.model_dump_json()


@patch("backend.app.core.auth.requests.get")
def test_unrecognized_tier_not_assumed_free(get: Mock) -> None:
    get.return_value = Mock(status_code=200, json=lambda: {"subscription": {"tier": "unknown"}})
    assert verify_access(TEST_KEY).status == "UNAVAILABLE"


@patch("backend.app.core.auth.requests.get")
def test_network_exception_secret_is_not_logged(get: Mock) -> None:
    get.side_effect = requests.ConnectionError(f"URL contains {TEST_KEY}")
    result = verify_access(TEST_KEY)
    assert result.status == "UNAVAILABLE"
    assert TEST_KEY not in result.model_dump_json()
