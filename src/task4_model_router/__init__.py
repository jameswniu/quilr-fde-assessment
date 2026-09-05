"""Task 4: token aware rate limiting and model failover for an LLM gateway."""

from task4_model_router.errors import GatewayError, GatewayErrorCode
from task4_model_router.providers import CompletionRequest, CompletionResult
from task4_model_router.rate_limiter import SlidingWindowRateLimiter
from task4_model_router.router import ModelRouter

__all__ = [
    "CompletionRequest",
    "CompletionResult",
    "GatewayError",
    "GatewayErrorCode",
    "ModelRouter",
    "SlidingWindowRateLimiter",
]
