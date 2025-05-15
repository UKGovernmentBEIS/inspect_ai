import time
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def execution_timer(name: str | None = None) -> Iterator[None]:
    start_time = time.perf_counter()
    yield
    end_time = time.perf_counter()
    print(
        f"{name if name else ''} execution time: {end_time - start_time:.6f} seconds".strip()
    )
