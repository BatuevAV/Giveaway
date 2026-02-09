"""Client for generating giveaway drafts via Ollama."""

import json
import logging
import re
import ast
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
        # Some models return JSON as string literal; parse one more time.
        if isinstance(parsed, str):
            try:
                parsed2 = json.loads(parsed)
                if isinstance(parsed2, dict):
                    return parsed2
            except Exception:
                pass
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
        # Relaxed fallback for python-like dicts with single quotes.
        try:
            parsed = ast.literal_eval(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None

    return None


def _extract_sections_fallback(text: str) -> Optional[dict]:
    """
    Fallback parser for human-formatted responses:
    "Название: ...", "Описание: ...", "Призы: ...", "Условия участия: ..."
    """
    if not text:
        return None

    labels = {
        "title": [r"название", r"title"],
        "description": [r"описание", r"description"],
        "prizes": [r"призы", r"приз", r"prizes", r"prize"],
        "participation_rules": [r"условия участия", r"условия", r"rules", r"participation rules"],
    }

    # Find marker positions.
    markers = []
    for field, variants in labels.items():
        pattern = r"(?im)^\s*(?:[-*]\s*)?(?:\*{0,2})(" + "|".join(variants) + r")(?:\*{0,2})\s*[:\-]\s*"
        for match in re.finditer(pattern, text):
            markers.append((match.start(), match.end(), field))

    if not markers:
        return None

    markers.sort(key=lambda x: x[0])
    values = {}
    for i, (_, content_start, field) in enumerate(markers):
        next_start = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        chunk = text[content_start:next_start].strip()
        if chunk:
            values[field] = chunk

    # Ensure all required fields exist.
    cleaned = {
        "title": str(values.get("title", "")).strip(),
        "description": str(values.get("description", "")).strip(),
        "prizes": str(values.get("prizes", "")).strip(),
        "participation_rules": str(values.get("participation_rules", "")).strip(),
    }
    if all(cleaned.values()):
        return cleaned
    return None


def _build_heuristic_draft_from_brief(brief: str, raw_response: str = "") -> dict:
    """
    Last-resort fallback: build a valid draft from user brief
    so flow can continue even if model response is unstructured.
    """
    source = (brief or "").strip()
    if not source:
        source = "Розыгрыш для подписчиков сообщества"

    # Title: compact first part of brief.
    title = source.split(".")[0].split("\n")[0].strip()
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    if len(title) < 8:
        title = "Розыгрыш для подписчиков"

    # Simple prizes detection.
    combined = f"{brief}\n{raw_response}".lower()
    prizes_parts = []
    if "сертификат" in combined:
        prizes_parts.append("Сертификат на 500 ₽ в компьютерный клуб")
    if "сувенир" in combined:
        prizes_parts.append("Фирменные сувениры клуба")
    if not prizes_parts:
        prizes_parts.append("Подарки от организатора")
    prizes = ", ".join(prizes_parts)

    description = (
        "Мы подготовили розыгрыш для подписчиков нашего сообщества.\n"
        "Подробности и условия участия — ниже."
    )

    rules = (
        "1) Быть подписанным на канал/сообщество клуба.\n"
        "2) Нажать кнопку участия под постом розыгрыша.\n"
        "3) Дождаться окончания розыгрыша и объявления результатов."
    )

    return {
        "title": title,
        "description": description,
        "prizes": prizes,
        "participation_rules": rules,
    }


class OllamaClient:
    """Minimal async Ollama HTTP client."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 45,
        max_tokens: int = 260,
        temperature: float = 0.3,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature

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
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        url = f"{self.base_url}/api/generate"
        timeout = httpx.Timeout(self.timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.ReadTimeout as exc:
                fast_model = await self._get_fastest_available_model(client)
                if fast_model and fast_model != payload["model"]:
                    logger.warning(
                        "Timeout with model '%s'. Retrying once with faster model '%s'.",
                        payload["model"],
                        fast_model
                    )
                    retry_payload = dict(payload)
                    retry_payload["model"] = fast_model
                    retry_timeout = httpx.Timeout(self.timeout_seconds + 120)
                    retry_client = httpx.AsyncClient(timeout=retry_timeout)
                    try:
                        try:
                            retry_response = await retry_client.post(url, json=retry_payload)
                            retry_response.raise_for_status()
                            data = retry_response.json()
                        finally:
                            await retry_client.aclose()
                    except Exception as retry_exc:
                        raise RuntimeError(
                            f"Превышено время ожидания ответа Ollama ({self.timeout_seconds} сек) "
                            f"и повторная попытка с моделью '{fast_model}' тоже не удалась. "
                            "Увеличьте OLLAMA_TIMEOUT_SECONDS или установите более быструю модель."
                        ) from retry_exc
                else:
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
            parsed = _extract_sections_fallback(raw)
        if not parsed:
            logger.warning(
                "Ollama response is non-JSON and non-sectioned. Using heuristic draft. Raw sample: %s",
                (raw or "")[:500]
            )
            parsed = _build_heuristic_draft_from_brief(brief=brief, raw_response=raw)

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

    async def _get_fastest_available_model(self, client: httpx.AsyncClient) -> Optional[str]:
        """
        Returns the smallest available model by parameter size (e.g. 3B < 7B).
        Falls back to first available model if size metadata is absent.
        """
        try:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models") or []
            if not models:
                return None

            def model_size_score(model_item: dict) -> float:
                details = model_item.get("details") or {}
                raw_size = str(details.get("parameter_size", "")).strip().upper()
                match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([BM])$", raw_size)
                if not match:
                    return float("inf")
                value = float(match.group(1))
                unit = match.group(2)
                if unit == "M":
                    return value / 1000.0
                return value

            sorted_models = sorted(models, key=model_size_score)
            best = sorted_models[0]
            return best.get("name") or best.get("model")
        except Exception as exc:
            logger.error("Failed to select fastest model from Ollama tags: %s", exc)
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
