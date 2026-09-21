"""One error per thing that can go wrong, each with what the founder should see.

`message` is written for a person and goes over the wire. `detail` is for the log
and never leaves the process.
"""

from __future__ import annotations


class BieError(Exception):
    """Base class. Subclasses set code, status_code and retryable."""

    code = "error"
    status_code = 500
    retryable = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def as_payload(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


class IdeaTooShort(BieError):
    code = "idea_too_short"
    status_code = 422


class AttachmentRejected(BieError):
    code = "attachment_rejected"
    status_code = 400


class BudgetExceeded(BieError):
    code = "budget_exceeded"
    status_code = 402


class InvalidModelOutput(BieError):
    """The reply did not validate. Never patch it, never show it."""

    code = "invalid_model_output"
    status_code = 500
    retryable = True


class UpstreamError(BieError):
    code = "upstream_error"
    status_code = 502
    retryable = True


class UpstreamTimeout(BieError):
    code = "upstream_timeout"
    status_code = 502
    retryable = True


class RateLimited(BieError):
    code = "rate_limited"
    status_code = 502
    retryable = True
