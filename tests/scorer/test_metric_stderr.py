import contextlib
from typing import List, Optional

import numpy as np
import pytest

from inspect_ai.scorer._metric import ReducedScore, Score
from inspect_ai.scorer._metrics.std import hierarchical_bootstrap, stderr


@contextlib.contextmanager
def fixed_seed(seed=42):
    """Temporarily set numpy random seed"""
    state = np.random.get_state()
    np.random.seed(seed)
    try:
        yield
    finally:
        np.random.set_state(state)


def test_stderr_variance_hierarchy():
    """Test that within-cluster variance increases stderr even with same means"""
    with fixed_seed():
        # Case 1: No within-cluster variance, both clusters have mean 1.5
        scores_constant = [
            ReducedScore(value=1.5, children=[Score(value=1.5), Score(value=1.5)]),
            ReducedScore(value=1.5, children=[Score(value=1.5), Score(value=1.5)]),
        ]

        # Case 2: Within-cluster variance, both clusters still have mean 1.5
        scores_varying = [
            ReducedScore(value=1.5, children=[Score(value=1.0), Score(value=2.0)]),
            ReducedScore(value=1.5, children=[Score(value=1.0), Score(value=2.0)]),
        ]

        metric = stderr()
        stderr_constant = metric(scores_constant)
        stderr_varying = metric(scores_varying)

        # Stderr should be larger when there's within-cluster variance
        assert stderr_varying > stderr_constant


def test_stderr_constant():
    """When all values are identical, stderr should be 0"""
    with fixed_seed():
        scores = [
            ReducedScore(value=1.0, children=[Score(value=1.0)]),
            ReducedScore(value=1.0, children=[Score(value=1.0)]),
            ReducedScore(value=1.0, children=[Score(value=1.0)]),
        ]
        metric = stderr()
        result = metric(scores)
        assert result == pytest.approx(0)


def test_stderr_trivial_clusters():
    """Test with multiple clusters but only 1 member each"""
    with fixed_seed():
        scores = [
            ReducedScore(value=0.3, children=[Score(value=0.3)]),
            ReducedScore(value=0.8, children=[Score(value=0.8)]),
            ReducedScore(value=0.4, children=[Score(value=0.4)]),
        ]
        metric = stderr()
        result = metric(scores)
        # For [0.3, 0.8, 0.4]: std ≈ 0.216, sdt/√3 ≈ 0.124
        assert result == pytest.approx(0.124, rel=5 / 100)


def test_stderr_single_cluster():
    """Test with only one cluster but multiple members"""
    with fixed_seed():
        scores = [
            ReducedScore(
                value=0.5,
                children=[Score(value=0.3), Score(value=0.8), Score(value=0.4)],
            )
        ]
        metric = stderr()
        result = metric(scores)
        # Same as above but with different hierarchy structure
        # For [0.3, 0.8, 0.4]: std ≈ 0.216, sdt/√3 ≈ 0.124
        assert result == pytest.approx(0.124, rel=5 / 100)


def test_stderr_empty_cluster_raises():
    """Test that empty clusters raise ValueError"""
    scores = [
        ReducedScore(value=1.0, children=[]),
    ]
    metric = stderr()
    with pytest.raises(ValueError, match="requires non-empty clusters"):
        metric(scores)


def readable_hierarchical_bootstrap(
    scores: List[List[float]],
    n_bootstrap: int = 1000,
    random_state: Optional[int] = None,
) -> List[float]:
    """Readable implementation of hierarchical bootstrap using Python loops for clarity."""
    rng = np.random.default_rng(random_state)
    scores_array = np.array(scores)  # Shape: (n_clusters, n_members)
    bootstrap_means = []

    for _ in range(n_bootstrap):
        # Resample clusters using axis parameter
        sampled_clusters = rng.choice(
            scores_array, size=len(scores_array), replace=True, axis=0
        )

        # For each cluster, resample its members
        cluster_means = []
        for cluster_scores in sampled_clusters:
            resampled_members = rng.choice(
                cluster_scores, size=len(cluster_scores), replace=True
            )
            cluster_means.append(np.mean(resampled_members))

        # Calculate mean across clusters for this bootstrap sample
        bootstrap_mean = float(np.mean(cluster_means))

        bootstrap_means.append(bootstrap_mean)

    return bootstrap_means


def test_redable_matches_fast():
    """Test that the readable implementation of hierarchical bootstrap matches the fast implementation."""
    scores = [
        [2.0, 4.0, 8.0, 16.0],  # cluster 1
        [0.5, 0.7, 0.6, 0.8],  # cluster 2
        [2.1, 2.3, 2.0, 2.2],  # cluster 3
    ]

    # Parameters
    n_samples = 2000
    random_seed = 42
    relative_tolerance = 0.05

    # Run both implementations
    fast_results = hierarchical_bootstrap(
        scores, num_samples=n_samples, random_state=random_seed
    )

    readable_results = readable_hierarchical_bootstrap(
        scores, n_bootstrap=n_samples, random_state=random_seed
    )

    # Compare mean and standard deviation
    assert np.mean(fast_results) == pytest.approx(
        np.mean(readable_results), rel=relative_tolerance
    )
    assert np.std(fast_results) == pytest.approx(
        np.std(readable_results), rel=relative_tolerance
    )

    # Compare quartiles
    q = [0.25, 0.5, 0.75]
    fast_quantiles = np.quantile(fast_results, q)
    readable_quantiles = np.quantile(readable_results, q)
    for fq, rq in zip(fast_quantiles, readable_quantiles):
        assert fq == pytest.approx(rq, rel=relative_tolerance)
