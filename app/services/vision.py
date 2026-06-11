from __future__ import annotations

import base64

import httpx

from app.core.config import Settings, get_settings


class VisionConfigurationError(RuntimeError):
    pass


class VisionResponseError(RuntimeError):
    pass


class ImageUnderstandingService:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client

    async def describe_image(self, content: bytes, content_type: str | None) -> str:
        if not content:
            raise VisionResponseError(
                "Image understanding failed because the uploaded file is empty."
            )
        mode = self.settings.vision_mode
        if mode is None:
            raise VisionConfigurationError(
                "Image understanding is not configured. Set VISION_MODE with a supported provider, "
                "or send the text from the image as a document."
            )
        mime_type = content_type or "image/jpeg"
        if mode == "openai":
            return await self._describe_openai(content, mime_type)
        if mode == "gemini":
            return await self._describe_gemini(content, mime_type)
        raise VisionConfigurationError(f"Unsupported VISION_MODE: {mode}")

    async def _describe_openai(self, content: bytes, mime_type: str) -> str:
        if not self.settings.openai_api_key:
            raise VisionConfigurationError("OPENAI_API_KEY is required when VISION_MODE=openai.")
        data_url = f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        async with self._client() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Extract all readable text and describe important visual "
                                        "context. Return concise plain text only."
                                    ),
                                },
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                },
            )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        if not text:
            raise VisionResponseError("Image understanding returned no readable content.")
        return text

    async def _describe_gemini(self, content: bytes, mime_type: str) -> str:
        if not self.settings.gemini_api_key:
            raise VisionConfigurationError("GEMINI_API_KEY is required when VISION_MODE=gemini.")
        async with self._client() as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-2.5-flash:generateContent",
                params={"key": self.settings.gemini_api_key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": (
                                        "Extract all readable text and describe important visual "
                                        "context. Return concise plain text only."
                                    )
                                },
                                {
                                    "inline_data": {
                                        "mime_type": mime_type,
                                        "data": base64.b64encode(content).decode("ascii"),
                                    }
                                },
                            ],
                        }
                    ]
                },
            )
        response.raise_for_status()
        parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise VisionResponseError("Image understanding returned no readable content.")
        return text

    def _client(self):
        if self.http_client is not None:
            return _ExternalClientContext(self.http_client)
        return httpx.AsyncClient(timeout=120)


class _ExternalClientContext:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *args: object) -> None:
        return None
