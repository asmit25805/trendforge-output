import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, TypeVar

from src.core.models import Config

T = TypeVar("T")
R = TypeVar("R")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _discover_config(start_dir: Path) -> Path:
    """
    Walk up from ``start_dir`` looking for a ``config.json`` file.
    Returns the first match; raises FileNotFoundError if none is found.
    """
    current = start_dir.resolve()
    for _ in range(10):
        candidate = current / "config.json"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise FileNotFoundError("Configuration file 'config.json' not found")


def _load_config() -> Config:
    """
    Load the global ``Config`` from the nearest ``config.json``.
    Falls back to environment defaults if the file is missing.
    """
    try:
        config_path = _discover_config(Path.cwd())
        return Config.parse_file(config_path)
    except FileNotFoundError:
        # Minimal fallback – useful for tests that do not ship a config file.
        return Config(
            model="gpt-4o-mini",
            system_prompt_path=Path("system_prompt.txt"),
            max_workers=os.cpu_count() or 4,
            rate_limit=60,
            cache_path=Path("cache.db"),
        )


def _default_max_workers() -> int:
    """
    Resolve the default number of workers from the loaded configuration.
    """
    cfg = _load_config()
    return max(1, cfg.max_workers)


def exponential_backoff(
    *,
    base: float = 0.5,
    factor: float = 2.0,
    max_delay: float = 30.0,
    max_retries: int = 5,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that retries an async function with exponential back‑off.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_retries - 1:
                        logger.error(
                            "Exhausted retries for %s after %d attempts: %s",
                            func.__name__,
                            max_retries,
                            exc,
                        )
                        raise
                    logger.warning(
                        "Retry %d/%d for %s after %s seconds: %s",
                        attempt + 1,
                        max_retries,
                        func.__name__,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * factor, max_delay)

        return wrapper

    return decorator


class BoundedThreadPoolExecutor(ThreadPoolExecutor):
    """
    ThreadPoolExecutor that limits the number of queued tasks via a semaphore.
    """

    def __init__(self, max_workers: Optional[int] = None, queue_size: int = 0):
        """
        Initialise the executor.

        * ``max_workers`` – number of worker threads; defaults to config or CPU count.
        * ``queue_size`` – maximum number of pending submissions; 0 means unlimited.
        """
        resolved_workers = max_workers or _default_max_workers()
        super().__init__(max_workers=resolved_workers)
        self._semaphore = asyncio.Semaphore(queue_size) if queue_size > 0 else None

    def submit(self, fn: Callable[..., R], *args: Any, **kwargs: Any) -> Future[R]:
        """
        Submit a callable to the pool, respecting the optional queue size limit.
        """
        if self._semaphore is None:
            return super().submit(fn, *args, **kwargs)

        async def _run():
            async with self._semaphore:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, fn, *args, **kwargs)

        return asyncio.run(_run())

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """
        Shut down the executor, releasing the semaphore if present.
        """
        if self._semaphore is not None:
            # No explicit release needed; the semaphore will be garbage‑collected.
            self._semaphore = None
        super().shutdown(wait=wait, cancel_futures=cancel_futures)


def bounded_executor(
    max_workers: Optional[int] = None, *, queue_size: int = 0
) -> BoundedThreadPoolExecutor:
    """
    Factory that returns a ``BoundedThreadPoolExecutor`` with sensible defaults.
    """
    return BoundedThreadPoolExecutor(max_workers=max_workers, queue_size=queue_size)


async def run_in_thread(fn: Callable[..., R], *args: Any, **kwargs: Any) -> R:
    """
    Execute ``fn`` in a bounded thread pool and return its result.
    """
    executor = bounded_executor()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, fn, *args, **kwargs)


def parallel_map(
    func: Callable[[T], R],
    iterable: Iterable[T],
    *,
    max_workers: Optional[int] = None,
    queue_size: int = 0,
) -> List[R]:
    """
    Apply ``func`` to each element of ``iterable`` using a bounded thread pool.
    Returns a list preserving the original order.
    """
    executor = bounded_executor(max_workers=max_workers, queue_size=queue_size)
    futures: List[Future[R]] = [executor.submit(func, item) for item in iterable]
    results: List[R] = []
    for future in futures:
        results.append(future.result())
    executor.shutdown()
    return results


@exponential_backoff()
async def retry_async(
    coro: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Execute an awaitable ``coro`` with exponential back‑off retry logic.
    """
    return await coro(*args, **kwargs)


__all__ = [
    "bounded_executor",
    "run_in_thread",
    "parallel_map",
    "exponential_backoff",
    "retry_async",
    "BoundedThreadPoolExecutor",
]