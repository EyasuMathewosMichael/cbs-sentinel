"""Common runtime safeguards around asynchronous CBS adapter calls."""

import asyncio
from collections.abc import Awaitable

from sentinel.adapters.cbs.contracts import (
    CBSAuthenticationError,
    CBSOperationTimeout,
    CBSUnavailableError,
)


async def execute_cbs_call[Result](
    operation: Awaitable[Result], *, timeout_seconds: float
) -> Result:
    """Apply a bounded timeout and normalize common transport failures.

    Authentication remains the concrete adapter's responsibility. Adapters
    should raise CBSAuthenticationError rather than exposing provider details.
    No database or ledger access is performed by this boundary.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    try:
        return await asyncio.wait_for(operation, timeout=timeout_seconds)
    except TimeoutError as error:
        raise CBSOperationTimeout("CBS operation timed out") from error
    except (ConnectionError, OSError) as error:
        raise CBSUnavailableError("CBS endpoint is unavailable") from error
    except CBSAuthenticationError:
        raise
