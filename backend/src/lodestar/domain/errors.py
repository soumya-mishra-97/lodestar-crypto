"""Domain and application errors. The HTTP layer maps these to problem responses."""


class LodestarError(Exception):
    """Base class for all expected (handled) errors."""

    code = "internal_error"


class NotFoundError(LodestarError):
    code = "not_found"


class ConflictError(LodestarError):
    code = "conflict"


class ValidationFailed(LodestarError):
    code = "validation_failed"


class AuthenticationError(LodestarError):
    code = "unauthenticated"


class AuthorizationError(LodestarError):
    code = "forbidden"


class RateLimitedError(LodestarError):
    code = "rate_limited"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailable(LodestarError):
    """An upstream data provider failed after retries or its circuit is open."""

    code = "provider_unavailable"


class InsufficientData(LodestarError):
    """Not enough verified data to produce a trustworthy analysis."""

    code = "insufficient_data"


class LlmUnavailable(LodestarError):
    """The LLM could not produce a usable answer (rate limit, refusal, outage, bad output)."""

    code = "llm_unavailable"
