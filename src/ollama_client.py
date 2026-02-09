"""Client for generating giveaway drafts via Ollama."""

import json
import logging
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> Optional[dict]:
    """Try to find and parse the first JSON object in model output."""
    if not text:
        return None

    text = text.strip()
    # Fast path: full response is JSON.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Fallback: extract first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = text[start:end + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None

    return None


class OllamaClient:
    """Minimal async Ollama HTTP client."""

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 45):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_giveaway_draft(
        self,
        brief: str,
        revision_request: Optional[str] = None,
        current_draft: Optional[dict] = None,
    ) -> dict:
        """
        Generate a structured giveaway draft.

        Returns dict with required keys:
        - title
        - description
        - prizes
        - participation_rules
        """
        prompt = self._build_prompt(brief, revision_request, current_draft)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        url = f"{self.base_url}/api/generate"
        timeout = httpx.Timeout(self.timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.ReadTimeout as exc:
                raise RuntimeError(
                    f"Превышено время ожидания ответа Ollama ({self.timeout_seconds} сек). "
                    "Увеличьте OLLAMA_TIMEOUT_SECONDS или используйте более быструю модель."
                ) from exc
            except httpx.HTTPStatusError as exc:
                # Ollama returns 404 both for wrong path and for "model not found".
                # Here we handle the common "model not found" case gracefully.
                if exc.response is not None and exc.response.status_code == 404:
                    try:
                        error_payload = exc.response.json()
                    except Exception:
                        error_payload = {}
                    error_text = str(error_payload.get("error", "")).strip()
                    if "model" in error_text and "not found" in error_text:
                        fallback_model = await self._get_first_available_model(client)
                        if fallback_model:
                            logger.warning(
                                "Configured model '%s' not found. Falling back to '%s'.",
                                self.model,
                                fallback_model
                            )
                            payload["model"] = fallback_model
                            try:
                                response = await client.post(url, json=payload)
                                response.raise_for_status()
                                data = response.json()
                            except httpx.ReadTimeout as timeout_exc:
                                raise RuntimeError(
                                    f"Модель '{fallback_model}' отвечает слишком долго "
                                    f"(таймаут {self.timeout_seconds} сек). "
                                    "Увеличьте OLLAMA_TIMEOUT_SECONDS."
                                ) from timeout_exc
                        else:
                            raise RuntimeError(
                                f"Модель '{self.model}' не найдена в Ollama и не удалось определить доступные модели."
                            ) from exc
                    else:
                        raise RuntimeError(
                            f"Ollama вернул 404 по URL {url}. Проверьте OLLAMA_BASE_URL."
                        ) from exc
                else:
                    raise RuntimeError(f"Ollama request failed: {exc}") from exc

        raw = data.get("response", "")
        parsed = _extract_json_object(raw)
        if not parsed:
            raise RuntimeError("AI returned non-JSON response")

        cleaned = {
            "title": str(parsed.get("title", "")).strip(),
            "description": str(parsed.get("description", "")).strip(),
            "prizes": str(parsed.get("prizes", "")).strip(),
            "participation_rules": str(parsed.get("participation_rules", "")).strip(),
        }

        missing = [key for key, value in cleaned.items() if not value]
        if missing:
            raise RuntimeError(f"AI response missing required fields: {', '.join(missing)}")

        return cleaned

    async def _get_first_available_model(self, client: httpx.AsyncClient) -> Optional[str]:
        """Returns first installed model from Ollama /api/tags."""
        try:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models") or []
            if not models:
                return None
            first = models[0]
            return first.get("name") or first.get("model")
        except Exception as exc:
            logger.error("Failed to fetch available models from Ollama: %s", exc)
            return None

    def _build_prompt(
        self,
        brief: str,
        revision_request: Optional[str],
        current_draft: Optional[dict],
    ) -> str:
        lines = [
            "You are an assistant for a Telegram giveaway bot.",
            "Generate Russian text for a giveaway draft.",
            "Return strictly JSON object with keys:",
            "title, description, prizes, participation_rules",
            "Do not include markdown code fences.",
            "Keep the style clear, practical, and human.",
            "",
            f"User brief: {brief}",
        ]

        if current_draft:
            lines.extend([
                "",
                "Current draft JSON:",
                json.dumps(current_draft, ensure_ascii=False),
            ])

        if revision_request:
            lines.extend([
                "",
                f"Revision request: {revision_request}",
                "Update the draft accordingly.",
            ])

        return "\n".join(lines)
