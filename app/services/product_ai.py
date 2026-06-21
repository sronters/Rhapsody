from __future__ import annotations

import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings, get_settings
from app.schemas.memory import MemorySource


class AIConfigurationError(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    pass


class ExtractedMeetingTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=320)
    assignee: str | None = Field(default=None, max_length=160)
    deadline: str | None = Field(default=None, max_length=120)
    priority: str | None = Field(default=None, max_length=40)
    source_text: str | None = Field(default=None, max_length=1200)


class ExtractedMeetingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=320)
    rationale: str = Field(default="", max_length=12000)
    source_text: str | None = Field(default=None, max_length=1200)


class ExtractedMeetingRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=320)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    mitigation: str | None = None
    source_text: str | None = Field(default=None, max_length=1200)


class LLMMeetingExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=12000)
    tasks: list[ExtractedMeetingTask] = Field(default_factory=list)
    decisions: list[ExtractedMeetingDecision] = Field(default_factory=list)
    risks: list[ExtractedMeetingRisk] = Field(default_factory=list)
    follow_up: str = Field(default="", max_length=8000)


class ProductAIClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client

    async def extract_meeting(self, transcript: str, locale: str = "en") -> LLMMeetingExtraction:
        prompt = build_meeting_extraction_prompt(transcript, locale)
        text = await self.generate(prompt)
        try:
            return parse_meeting_extraction(text)
        except AIResponseError:
            repair_prompt = build_json_repair_prompt(text)
            repaired_text = await self.generate(repair_prompt)
            return parse_meeting_extraction(repaired_text)

    async def answer_question(
        self,
        question: str,
        sources: list[MemorySource],
        locale: str = "en",
    ) -> str:
        if not sources:
            raise AIResponseError("No memory sources are available for this question.")
        return await self.generate(build_memory_answer_prompt(question, sources, locale))

    async def generate(self, prompt: str) -> str:
        mode = self.settings.ai_mode
        if mode is None:
            raise AIConfigurationError("AI_MODE is not configured.")
        async with self._client() as client:
            if mode == "openai":
                return await self._generate_openai_compatible(
                    client,
                    url="https://api.openai.com/v1/chat/completions",
                    api_key=self._required(self.settings.openai_api_key, "OPENAI_API_KEY"),
                    model="gpt-4o-mini",
                    prompt=prompt,
                )
            if mode == "openrouter":
                return await self._generate_openai_compatible(
                    client,
                    url="https://openrouter.ai/api/v1/chat/completions",
                    api_key=self._required(self.settings.openrouter_api_key, "OPENROUTER_API_KEY"),
                    model="openai/gpt-4o-mini",
                    prompt=prompt,
                )
            if mode == "gemini":
                return await self._generate_gemini(
                    client,
                    self._required(self.settings.gemini_api_key, "GEMINI_API_KEY"),
                    prompt,
                )
            if mode == "ollama":
                return await self._generate_ollama(client, prompt)
        raise AIConfigurationError(f"Unsupported AI_MODE: {mode}")

    def _client(self):
        if self.http_client is not None:
            return _ExternalClientContext(self.http_client)
        return httpx.AsyncClient(timeout=60)

    @staticmethod
    def _required(value: str | None, name: str) -> str:
        if not value:
            raise AIConfigurationError(f"{name} is required for the selected AI_MODE.")
        return value

    async def _generate_openai_compatible(
        self,
        client: httpx.AsyncClient,
        url: str,
        api_key: str,
        model: str,
        prompt: str,
    ) -> str:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def _generate_gemini(self, client: httpx.AsyncClient, api_key: str, prompt: str) -> str:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash:generateContent",
            params={"key": api_key},
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
        )
        response.raise_for_status()
        parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)

    async def _generate_ollama(self, client: httpx.AsyncClient, prompt: str) -> str:
        response = await client.post(
            f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
            json={"model": self.settings.ollama_model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        text = response.json().get("response")
        if not text:
            raise AIResponseError("Ollama returned an empty response.")
        return text


class _ExternalClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *args: object) -> None:
        return None


def parse_meeting_extraction(text: str) -> LLMMeetingExtraction:
    try:
        payload = json.loads(extract_json_object(text))
        return LLMMeetingExtraction.model_validate(normalize_meeting_payload(payload))
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise AIResponseError("The AI response was not valid meeting JSON.") from exc


def normalize_meeting_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    if normalized.get("follow_up") is None:
        normalized["follow_up"] = ""
    decisions = normalized.get("decisions")
    if isinstance(decisions, list):
        normalized["decisions"] = [
            {
                **decision,
                "rationale": "" if decision.get("rationale") is None else decision.get("rationale"),
            }
            if isinstance(decision, dict)
            else decision
            for decision in decisions
        ]
    return normalized


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found.")
    return stripped[start : end + 1]


def build_meeting_extraction_prompt(transcript: str, locale: str = "en") -> str:
    language = "Russian" if locale.startswith("ru") else "English"
    return (
        "Extract meeting intelligence from the transcript. Return only strict JSON exactly "
        "matching this schema: {\"summary\": string, \"tasks\": [{\"title\": string, "
        "\"assignee\": string|null, \"deadline\": string|null, "
        "\"priority\": string|null, \"source_text\": string|null}], "
        "\"decisions\": [{\"title\": string, \"rationale\": string, "
        "\"source_text\": string|null}], \"risks\": [{\"title\": string, "
        "\"severity\": \"low|medium|high|critical\", \"mitigation\": string|null, "
        "\"source_text\": string|null}], "
        "\"follow_up\": string}. Do not include markdown. Do not invent facts not supported by "
        f"the transcript. Write all human-readable values in {language}; keep JSON keys and "
        "enum-like values stable.\n\n"
        f"Transcript:\n{transcript}"
    )


def build_json_repair_prompt(text: str) -> str:
    return (
        "Repair this response into strict JSON with keys summary, tasks, decisions, risks, "
        "follow_up. Task objects must use title, assignee, deadline, priority, source_text. "
        "Decision objects must use title, rationale, source_text. Risk objects must use title, "
        "severity, mitigation, source_text. Return only JSON.\n\n"
        f"Response:\n{text}"
    )


def build_memory_answer_prompt(
    question: str,
    sources: list[MemorySource],
    locale: str = "en",
) -> str:
    language = "Russian" if locale.startswith("ru") else "English"
    source_text = "\n\n".join(
        f"[{index}] {source.source_type} — {source.source_title}\n{source.excerpt}"
        for index, source in enumerate(sources, start=1)
    )
    return (
        "Answer the question using only the provided Rhapsody sources. Cite source numbers. "
        f"Write the answer in {language}.\n\n"
        f"Sources:\n{source_text}\n\nQuestion: {question}\nAnswer:"
    )
