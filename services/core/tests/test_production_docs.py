"""Operational notes for queued consent email behavior."""

from pathlib import Path


def test_production_plan_covers_consent_email_cancellation_and_polling_limits() -> None:
    plan = Path(__file__).resolve().parents[3] / "docs" / "PRODUCTION.md"
    text = plan.read_text(encoding="utf-8")

    assert "when the person's contact address changes" in text
    assert "The dialog checks at most 20 times" in text
