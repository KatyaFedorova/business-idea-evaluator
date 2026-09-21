"""T013 — every failure has a stable code, an HTTP status and a retryable flag."""

from __future__ import annotations

import pytest

from bie.errors import (
    AttachmentRejected,
    BieError,
    BudgetExceeded,
    IdeaTooShort,
    InvalidModelOutput,
    RateLimited,
    UpstreamError,
    UpstreamTimeout,
)

EXPECTED = [
    (IdeaTooShort, "idea_too_short", 422, False),
    (AttachmentRejected, "attachment_rejected", 400, False),
    (BudgetExceeded, "budget_exceeded", 402, False),
    (InvalidModelOutput, "invalid_model_output", 500, True),
    (UpstreamError, "upstream_error", 502, True),
    (UpstreamTimeout, "upstream_timeout", 502, True),
    (RateLimited, "rate_limited", 502, True),
]


@pytest.mark.parametrize(("cls", "code", "status", "retryable"), EXPECTED)
def test_error_contract(cls, code, status, retryable):
    err = cls("something went wrong")
    assert isinstance(err, BieError)
    assert err.code == code
    assert err.status_code == status
    assert err.retryable is retryable
    assert err.message == "something went wrong"


def test_internal_detail_is_kept_off_the_wire():
    err = UpstreamError("We could not reach the evaluator.", detail="api_key=sk-ant-secret")
    payload = err.as_payload()
    assert payload == {
        "error": {
            "code": "upstream_error",
            "message": "We could not reach the evaluator.",
            "retryable": True,
        }
    }
    assert "sk-ant-secret" not in str(payload)
    assert err.detail == "api_key=sk-ant-secret"
