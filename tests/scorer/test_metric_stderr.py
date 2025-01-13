import pytest

from inspect_ai.scorer._metric import Score, ReducedScore
from inspect_ai.scorer._metrics.std import stderr


"""
Comparisons to ``statsmodels`` are done using the following code:
```python
import pandas as pd
import statsmodels.api as sm
def cluster_se(data: pd.DataFrame) -> float:
    # Add constant column of 1s.
    # We are running a trivial regression where we only estimate the y-intercept
    data['constant'] = 1

    model = sm.OLS(data['y'], data[['constant']])

    model = model.fit().get_robustcov_results(
        cov_type='cluster',
        groups=data['cluster_ids'],
    )
    assert len(model.bse) == 1
    return model.bse[0]
```
"""

def test_stderr_single_score():
    """Test stderr with a single score"""
    scores = [
        ReducedScore(value=1.0, children=[Score(value=1.0)])
    ]

    metric = stderr()
    result = metric(scores)

    assert result == 0.0


def test_stderr_empty_cluster():
    """Test stderr raises error with empty clusters"""
    scores = [
        ReducedScore(value=1.0, children=[]),
        ReducedScore(value=2.0, children=[Score(value=2.0)])
    ]

    metric = stderr()
    with pytest.raises(ValueError, match="Clustered standard error requires non-empty clusters"):
        metric(scores)


def test_stderr_binary_outcomes():
    """
    Test clustered SE with binary outcomes (0/1) across 3 clusters.

    Statsmodels verification:
    ```python
    data = pd.DataFrame({
        "y": [1, 1, 0, 0, 1, 0],
        "cluster_ids": [1, 1, 2, 2, 3, 3]
    })
    print(cluster_se(data))
    ```
    """
    scores = [
        ReducedScore(value=1.0, children=[Score(value=1.0), Score(value=1.0)]),
        ReducedScore(value=0.0, children=[Score(value=0.0), Score(value=0.0)]),
        ReducedScore(value=0.5, children=[Score(value=1.0), Score(value=0.0)])
    ]

    metric = stderr()
    result = metric(scores)

    expected = 0.28867513459481303  # from statsmodels

    assert pytest.approx(result) == expected
