"""Shared safe failures for voice requests and entry resource ownership."""

from dataclasses import dataclass
from enum import Enum


class FailureCategory(Enum):
    """Fixed diagnostic categories, never supplied by service response text."""

    HTTP = "http"
    CONNECTION = "connection"
    READ = "read"
    TIMEOUT = "timeout"


class FailurePhase(Enum):
    """The HTTP operation that failed."""

    ACQUIRE = "acquire"
    READ = "read"


@dataclass(frozen=True)
class FailureDiagnostic:
    """Allow only fixed labels and an integer HTTP status in diagnostics."""

    category: FailureCategory
    phase: FailurePhase
    http_status: int | None = None

    def __post_init__(self):
        if type(self.category) is not FailureCategory or type(self.phase) is not FailurePhase:
            raise ValueError("Invalid failure category or phase")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise ValueError("Invalid HTTP status")


class STTError(Exception):
    """A voice service request failed; messages must not contain request contents."""

    def __init__(self, *args, diagnostic: FailureDiagnostic | None = None):
        super().__init__(*args)
        if diagnostic is not None and type(diagnostic) is not FailureDiagnostic:
            raise ValueError("Invalid failure diagnostic")
        self.diagnostic = diagnostic


def safe_failure_detail(error: Exception) -> str:
    """Format allowlisted metadata only; ignore exception text and causes."""
    diagnostic = error.diagnostic if isinstance(error, STTError) else None
    if type(diagnostic) is not FailureDiagnostic:
        return "category=unclassified"
    # Revalidate at the log boundary even if exception metadata was replaced.
    if (
        type(diagnostic.category) is not FailureCategory
        or type(diagnostic.phase) is not FailurePhase
    ):
        return "category=unclassified"
    status = diagnostic.http_status
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        return "category=unclassified"
    detail = f"category={diagnostic.category.value} phase={diagnostic.phase.value}"
    return f"{detail} http_status={status}" if status is not None else detail


class AuthenticationError(STTError):
    """The service rejected authentication."""


class ResponseError(STTError):
    """The response is malformed, unsupported, empty, or exceeds a limit."""


class EntryUnavailableError(STTError):
    """The entry is paused or closed and cannot admit a new request."""


class ShutdownError(STTError):
    """Owned resources could not be released within the entry shutdown contract."""
