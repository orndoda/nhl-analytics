"""Shared NHL API client plumbing: construction and retry-on-transient-error."""

from __future__ import annotations

import random
import time
from typing import Callable

from nhlpy import NHLClient
from nhlpy.http_client import RateLimitExceededException, ServerErrorException

# Errors worth retrying: transient rate limiting / server hiccups.
RETRYABLE_EXCEPTIONS = (RateLimitExceededException, ServerErrorException)


def build_client(debug: bool = False) -> NHLClient:
    return NHLClient(debug=debug)


def call_with_retry(fn: Callable, *args, max_retries: int = 5, base_delay: float = 1.5, **kwargs):
    """Call `fn`, retrying with exponential backoff on rate-limit/server errors."""
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except RETRYABLE_EXCEPTIONS:
            if attempt == max_retries:
                raise
            time.sleep(base_delay * (2**attempt) + random.uniform(0, 0.5))
