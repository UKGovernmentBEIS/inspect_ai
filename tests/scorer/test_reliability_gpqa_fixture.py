"""Regression test for `reliability.paired_delta` on a real GPQA Diamond run.

Fixture: tests/scorer/data/gpqa_diamond_scores.csv — a scores-only derivative
of an inspect_evals/gpqa_diamond run, provided by ipfloater (Steph Linds) on
Inspect issue #4206. Apache-2.0; see the sibling .NOTICE file.

The load-bearing invariant: the 5 epochs per item must be aggregated to ONE
per-item mean per model *before* comparing the two models. On those 198
per-item pairs the paired analysis (exploiting the shared items) calls the gap
significant while the unpaired/independent-samples view of the identical numbers
does not:

    paired p < 0.05 < unpaired p

Counting the 5 epochs as independent observations (the bug #4206 guards against)
inflates n ~5x, collapses the standard error, and destroys the flip.
"""

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, mean, variance

import pytest

from inspect_ai.scorer import paired_delta

DATA = Path(__file__).parent / "data" / "gpqa_diamond_scores.csv"
MODEL_A = "openai/gpt-5-nano-2025-08-07"
MODEL_B = "openai/gpt-5.4-mini-2026-03-17"


def _load_per_item_means():
    """Load and epoch-aggregate the fixture.

    Aggregate the 5 epochs to one mean score per item, per model. Returns
    (items, a_means, b_means) aligned by item id.
    """
    scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with DATA.open(newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == ["item_id", "model_id", "score", "epoch"]
        for row in reader:
            scores[row["model_id"]][row["item_id"]].append(float(row["score"]))

    items = sorted(scores[MODEL_A])
    for model in (MODEL_A, MODEL_B):
        assert set(scores[model]) == set(items)
        assert all(len(scores[model][i]) == 5 for i in items)

    a = [mean(scores[MODEL_A][i]) for i in items]
    b = [mean(scores[MODEL_B][i]) for i in items]
    return items, a, b


def _independent_p(a, b):
    """Unpaired two-sample z-test on the same per-item means.

    Independent SE = sqrt(se_a^2 + se_b^2) — the maximum-variance comparison
    that paired_delta beats.
    """
    se = lambda x: math.sqrt(variance(x) / len(x))  # noqa: E731
    se_ind = math.sqrt(se(a) ** 2 + se(b) ** 2)
    z = (mean(a) - mean(b)) / se_ind
    return 2 * NormalDist().cdf(-abs(z)), se_ind


def test_fixture_shape():
    items, a, b = _load_per_item_means()
    assert len(items) == 198
    assert len(a) == len(b) == 198
    with DATA.open(newline="") as fh:
        assert sum(1 for _ in csv.reader(fh)) - 1 == 1980


def test_paired_vs_unpaired_significance_flip():
    """Assert the load-bearing significance flip.

    On epoch-aggregated per-item means, paired_delta says significant
    (p < 0.05) while the unpaired view of identical inputs does not (p > 0.05).
    """
    _items, a, b = _load_per_item_means()

    paired = paired_delta(a, b)
    unpaired_p, se_ind = _independent_p(a, b)

    # measured ~0.035 (paired) vs ~0.148 (unpaired); pin with tolerance.
    assert paired["p_value"] == pytest.approx(0.035, abs=0.01)
    assert unpaired_p == pytest.approx(0.148, abs=0.02)

    # the load-bearing flip.
    assert paired["p_value"] < 0.05 < unpaired_p

    # sanity: pairing materially shrinks the SE on the SAME delta.
    assert paired["delta"] == pytest.approx(mean(a) - mean(b))
    assert paired["stderr"] < se_ind
    design_effect = (se_ind / paired["stderr"]) ** 2
    assert design_effect > 1.8  # measured ~2.12 (per-item r ~ 0.53)
