from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.product_ai import (
    AIConfigurationError,
    AIResponseError,
    ProductAIClient,
    parse_meeting_extraction,
)


def test_parse_meeting_extraction_strict_json() -> None:
    extraction = parse_meeting_extraction(
        """
        {
          "summary": "Launch plan reviewed.",
          "tasks": [{
            "title": "Prepare checklist",
            "assignee": null,
            "deadline": "Friday",
            "priority": "high",
            "source_text": "Prepare checklist by Friday"
          }],
          "decisions": [{"title": "Use Supplier X", "rationale": "Meets compliance."}],
          "risks": [{"title": "Vendor approval", "severity": "high", "mitigation": "Escalate"}],
          "follow_up": "Confirm owners."
        }
        """
    )

    assert extraction.summary == "Launch plan reviewed."
    assert extraction.tasks[0].title == "Prepare checklist"
    assert extraction.decisions[0].title == "Use Supplier X"
    assert extraction.risks[0].severity == "high"


def test_invalid_meeting_json_raises_clear_error() -> None:
    with pytest.raises(AIResponseError, match="valid meeting JSON"):
        parse_meeting_extraction("not json")


def test_parse_meeting_extraction_accepts_null_optional_text_from_provider() -> None:
    extraction = parse_meeting_extraction(
        """
        {
          "summary": "Project launch was discussed.",
          "tasks": [],
          "decisions": [{"title": "Use Gemini", "rationale": null, "source_text": null}],
          "risks": [],
          "follow_up": null
        }
        """
    )

    assert extraction.decisions[0].rationale == ""
    assert extraction.follow_up == ""


@pytest.mark.asyncio
async def test_missing_ai_mode_raises_clear_error() -> None:
    client = ProductAIClient(settings=Settings(_env_file=None, ai_mode=None))

    with pytest.raises(AIConfigurationError, match="AI_MODE"):
        await client.generate("hello")


@pytest.mark.asyncio
async def test_missing_selected_provider_key_raises_clear_error() -> None:
    client = ProductAIClient(
        settings=Settings(_env_file=None, ai_mode="openai", openai_api_key=None)
    )

    with pytest.raises(AIConfigurationError, match="OPENAI_API_KEY"):
        await client.generate("hello")
