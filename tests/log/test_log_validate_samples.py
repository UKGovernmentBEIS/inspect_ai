from functools import partial
from pathlib import Path

import pytest

from inspect_ai.log import read_eval_log

long_log_path = Path(__file__).parent / "test_eval_log" / "long_log.eval"


@pytest.mark.benchmark
@pytest.mark.parametrize("skip_sample_validation", [True, False])
def test_read_eval_logs_skip_sample_validation(benchmark, skip_sample_validation: bool):
    read_eval_log_partial = partial(
        read_eval_log, long_log_path, skip_sample_validation=skip_sample_validation
    )
    result = benchmark(read_eval_log_partial)
