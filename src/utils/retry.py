"""Asynchronous Retry Utility with exponential backoff and jitter."""

import asyncio
from functools import wraps
import random
import sys
from typing import Any, Callable, Coroutine, Optional, Set, Tuple, Type, TypeVar

from src.utils.logger import get_logger

logger = get_logger("retry")

T = TypeVar("T")


def calculate_backoff(
    attempt: int,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_after: Optional[float] = None,
) -> float:
    """Calculate the delay before the next retry attempt."""
    if retry_after is not None and retry_after > 0:
        return min(retry_after, max_delay)

    delay = initial_delay * (backoff_factor ** (attempt - 1))
    if jitter:
        # Full jitter: uniform random delay between 0 and calculated exponential delay
        delay = random.uniform(initial_delay, delay)
    return min(delay, max_delay)


async def async_retry(
    coro_fn: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        ValueError,
        TypeError,
        KeyError,
        asyncio.CancelledError,
    ),
    logger_name: Optional[str] = None,
    **kwargs: Any,
) -> T:
    """Execute an asynchronous coroutine with exponential backoff retry.

    Args:
        coro_fn: Asynchronous function to execute.
        max_attempts: Maximum total attempts (1 means no retry).
        initial_delay: Initial sleep duration in seconds.
        max_delay: Maximum sleep duration in seconds.
        backoff_factor: Multiplier for exponential backoff.
        jitter: Whether to apply randomized jitter to avoid thundering herds.
        retryable_exceptions: Tuple of exceptions that warrant retry.
        non_retryable_exceptions: Tuple of exceptions that should terminate immediately.
        logger_name: Optional custom logger name.

    Returns:
        Result of coro_fn execution.

    Raises:
        The last exception raised by coro_fn if all attempts fail.
    """
    log = get_logger(logger_name) if logger_name else logger
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except non_retryable_exceptions as exc:
            log.debug("Non-retryable exception encountered: %s. Aborting retries.", exc)
            raise exc
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt >= max_attempts:
                log.warning(
                    "Operation '%s' failed on final attempt %d/%d: %s",
                    coro_fn.__name__,
                    attempt,
                    max_attempts,
                    exc,
                )
                break

            # Check if exception has retry_after attribute
            retry_after = getattr(exc, "retry_after", None)
            delay = calculate_backoff(
                attempt=attempt,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
                jitter=jitter,
                retry_after=retry_after,
            )

            log.warning(
                "Operation '%s' attempt %d/%d failed with %s: %s. Retrying in %.2fs...",
                coro_fn.__name__,
                attempt,
                max_attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Operation '{coro_fn.__name__}' failed without raising an exception.")


def with_retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (
        ValueError,
        TypeError,
        KeyError,
        asyncio.CancelledError,
    ),
) -> Callable[[Callable[..., Coroutine[Any, Any, T]]], Callable[..., Coroutine[Any, Any, T]]]:
    """Decorator for async functions providing exponential backoff retries."""

    def decorator(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await async_retry(
                fn,
                *args,
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
                jitter=jitter,
                retryable_exceptions=retryable_exceptions,
                non_retryable_exceptions=non_retryable_exceptions,
                **kwargs,
            )

        return wrapper

    return decorator
