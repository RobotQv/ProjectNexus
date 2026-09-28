"""Submission sanity only; these checks do not measure model accuracy."""

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parent / "evaluation"


@pytest.mark.parametrize(
    ("filename", "key", "count"),
    [
        ("questions.json", "questions", 24),
        ("dependency-rules.json", "rules", 8),
        ("extraction-samples.json", "samples", 4),
    ],
)
def test_draft_records_are_readable_and_unique(filename, key, count):
    data = json.loads((ROOT / filename).read_text(encoding="utf-8"))
    records = data[key]
    assert len(records) == count
    assert len({record["id"] for record in records}) == count
    assert "草稿" in data["description"]


def test_question_inventory_matches_the_review():
    records = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))["questions"]
    assert Counter(item["category"] for item in records) == {
        "material_qa": 10,
        "entity_status": 8,
        "mixed": 3,
        "insufficient": 3,
    }
    assert {item["project"] for item in records} == {"project-a", "project-b"}
    assert all(item["split"] == "test" for item in records)
    for item in records:
        if item["category"] == "insufficient":
            assert item["expected_evidence_anchors"] == []
