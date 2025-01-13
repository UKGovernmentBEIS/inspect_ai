import pytest

from inspect_ai.scorer._metric import ReducedScore, Score
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


def test_stderr_single_cluster():
    """Backward compatibility: previous implementation of stderr returned 0 for a single reduced score."""
    scores = [
        ReducedScore(
            value=2.5,
            children=[
                Score(value=1.0),
                Score(value=2.0),
                Score(value=3.0),
                Score(value=4.0),
            ],
        )
    ]

    metric = stderr()
    result = metric(scores)

    expected = 0
    assert pytest.approx(result) == expected


def test_stderr_singleton_clusters():
    """Test clustered SE with three clusters of size 1 each.

    This should reduce to the heteroskedasticity-robust standard error.

    Statsmodels verification:
    ```python
    data = pd.DataFrame({
        "y": [1.0, 2.0, 3.0],
        "cluster_ids": [1, 2, 3]
    })
    print(cluster_se(data))
    ```
    """
    scores = [
        ReducedScore(value=1.0, children=[Score(value=1.0)]),
        ReducedScore(value=2.0, children=[Score(value=2.0)]),
        ReducedScore(value=3.0, children=[Score(value=3.0)]),
    ]

    metric = stderr()
    result = metric(scores)

    expected = 0.5773502691896258  # from statsmodels
    assert pytest.approx(result) == expected


def test_stderr_empty_cluster():
    """Test stderr raises error with empty clusters"""
    scores = [
        ReducedScore(value=1.0, children=[]),
        ReducedScore(value=2.0, children=[Score(value=2.0)]),
    ]

    metric = stderr()
    with pytest.raises(
        ValueError, match="Clustered standard error requires non-empty clusters"
    ):
        metric(scores)


def test_stderr_identical_within_varied_between():
    """
    Test clustered SE where values are identical within clusters but vary between clusters.

    Statsmodels verification:
    ```python
    data = pd.DataFrame({
        "y": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 3.0],
        "cluster_ids": [1, 1, 2, 2, 3, 3, 3]
    })
    print(cluster_se(data))
    ```
    """
    scores = [
        ReducedScore(value=1.0, children=[Score(value=1.0), Score(value=1.0)]),
        ReducedScore(value=2.0, children=[Score(value=2.0), Score(value=2.0)]),
        ReducedScore(
            value=3.0, children=[Score(value=3.0), Score(value=3.0), Score(value=3.0)]
        ),
    ]

    metric = stderr()
    result = metric(scores)

    expected = 0.6040264729366833  # from statsmodels
    assert pytest.approx(result) == expected


def test_stderr_1():
    """Statsmodels verification.

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
        ReducedScore(value=0.5, children=[Score(value=1.0), Score(value=0.0)]),
    ]

    metric = stderr()
    result = metric(scores)

    expected = 0.28867513459481303  # from statsmodels

    assert pytest.approx(result) == expected


def test_stderr_2():
    """Statsmodels verification.

    ```python
    data = pd.DataFrame({
        "y": [9.0, 4.0, 11.0, 6.0, 13.0, 8.0],
        "cluster_ids": [1, 1, 2, 2, 3, 3]
    })
    print(cluster_se(data))
    ```
    """
    scores = [
        ReducedScore(value=6.5, children=[Score(value=9.0), Score(value=4.0)]),
        ReducedScore(value=8.5, children=[Score(value=11.0), Score(value=6.0)]),
        ReducedScore(value=10.5, children=[Score(value=13.0), Score(value=8.0)]),
    ]

    metric = stderr()
    result = metric(scores)

    expected = 1.1547005383792521  # from statsmodels
    assert pytest.approx(result) == expected
