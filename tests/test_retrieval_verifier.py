"""Verifier tolerates only tiny score ties, not changed evidence or real ordering."""

import pytest

from tests.evaluation.verify_retrieval_100 import verify_lexical_candidates


def test_float_tie_disclosed_without_rewriting_saved_order():
    saved = [{"chunk_id": "b", "score": 1.0}, {"chunk_id": "a", "score": 1.0}]
    changes = verify_lexical_candidates(["a", "b"], [1.0 + 1e-15, 1.0], saved)
    assert len(changes) == 2
    assert [r["chunk_id"] for r in saved] == ["b", "a"]


@pytest.mark.parametrize(
    "scores,saved",
    [
        ([2.0, 1.0], [{"chunk_id": "b", "score": 1.0}, {"chunk_id": "a", "score": 2.0}]),
        ([2.0, 1.0], [{"chunk_id": "a", "score": 9.0}, {"chunk_id": "b", "score": 1.0}]),
        ([2.0, 1.0], [{"chunk_id": "a", "score": 2.0}]),
        ([2.0, 1.0], [{"chunk_id": "a", "score": 2.0}, {"chunk_id": "a", "score": 2.0}]),
    ],
)
def test_real_score_order_or_candidate_change_fails(scores, saved):
    with pytest.raises(AssertionError):
        verify_lexical_candidates(["a", "b"], scores, saved)
