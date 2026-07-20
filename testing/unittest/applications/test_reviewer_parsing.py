from __future__ import annotations

from applications.incident_repair.schemas import ReviewSummaryModel


def test_reviewer_summary_requires_business_approval_field():
    review = ReviewSummaryModel.model_validate_json(
        '{"approved": false, "requirements_covered": ["pytest"], "issues": ["missing case"], "summary": "needs repair"}'
    )

    assert review.approved is False
    assert review.issues == ["missing case"]
