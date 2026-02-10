"""Client for generating giveaway drafts via Ollama."""

import json
import logging
import re
import ast
import hashlib
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


def _contains_emoji(text: str) -> bool:
    """Basic emoji presence check."""
    if not text:
        return False
    for ch in text:
        if ord(ch) > 0xFFFF:
            return True
    return False


def _normalize_title(title: str, brief: str = "", raw_response: str = "") -> str:
    """
    Make title short and catchy: 2-3 words + emoji.
    """
    combined = f"{brief}\n{raw_response}".lower()
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", title or "")
    seed_input = f"{combined}|{title}".encode("utf-8", errors="ignore")
    seed = int(hashlib.md5(seed_input).hexdigest()[:8], 16)

    def pick(options: list[str], shift: int = 0) -> str:
        if not options:
            return ""
        return options[(seed + shift) % len(options)]

    season_themes = {
        "autumn": {
            "keys": ["осен", "сентябр", "октябр", "ноябр"],
            "adjectives": ["Осенняя", "Золотая", "Листопадная", "Уютная"],
            "nouns": ["лихорадка", "оттепель", "волна", "охота", "удача"],
            "emoji": ["🍁", "🧡", "🍂"],
        },
        "spring": {
            "keys": ["весен", "март", "апрел", "май"],
            "adjectives": ["Весенняя", "Цветущая", "Свежая", "Солнечная"],
            "nouns": ["оттепель", "волна", "удача", "перезагрузка", "охота"],
            "emoji": ["🌸", "🌿", "☀️"],
        },
        "winter": {
            "keys": ["зим", "декабр", "январ", "феврал", "новогод"],
            "adjectives": ["Зимняя", "Снежная", "Морозная", "Праздничная"],
            "nouns": ["сказка", "удача", "лихорадка", "охота", "раздача"],
            "emoji": ["❄️", "🎄", "☃️"],
        },
        "summer": {
            "keys": ["лет", "июн", "июл", "август"],
            "adjectives": ["Летняя", "Жаркая", "Солнечная", "Яркая"],
            "nouns": ["раздача", "волна", "удача", "лихорадка", "охота"],
            "emoji": ["☀️", "🌴", "🔥"],
        },
    }

    gaming_theme = {
        "keys": ["игр", "гейм", "комп", "клуб", "steam", "кибер", "pc", "пк"],
        "adjectives": ["Жаркий", "Игровой", "Кибер", "Турбо", "Легендарный"],
        "nouns": ["розыгрыш", "джекпот", "дроп", "буст", "рейд"],
        "emoji": ["🔥", "🎮", "⚡"],
    }

    prize_theme = {
        "keys": ["сертификат", "подар", "приз", "сувенир", "бонус", "купон"],
        "adjectives": ["Щедрый", "Подарочный", "Призовой", "Большой", "Удачный"],
        "nouns": ["розыгрыш", "подаркопад", "джекпот", "раздача", "бонус"],
        "emoji": ["🎁", "🏆", "✨"],
    }

    default_theme = {
        "adjectives": ["Яркий", "Большой", "Горячий", "Супер", "Быстрый", "Мощный"],
        "nouns": ["розыгрыш", "джекпот", "подаркопад", "старт", "бонус"],
        "emoji": ["🎁", "✨", "🔥"],
    }

    chosen = None
    for theme in season_themes.values():
        if any(k in combined for k in theme["keys"]):
            chosen = theme
            break
    if not chosen and any(k in combined for k in gaming_theme["keys"]):
        chosen = gaming_theme
    if not chosen and any(k in combined for k in prize_theme["keys"]):
        chosen = prize_theme
    if not chosen:
        chosen = default_theme

    adjective = pick(chosen["adjectives"])
    noun = pick(chosen["nouns"], shift=3)
    emoji = pick(chosen["emoji"], shift=5)

    # If model already returned short title, keep its words (max 3 words).
    if 2 <= len(words) <= 3 and len(" ".join(words)) <= 36:
        base_words = [w.lower() for w in words]
        if base_words:
            base_words[0] = base_words[0].capitalize()
        base = " ".join(base_words)
    else:
        base = f"{adjective} {noun}"

    # Keep strict compact format.
    base_words = base.split()
    if len(base_words) > 3:
        base = " ".join(base_words[:3])
    if len(base_words) < 2:
        base = f"{adjective} {noun}"

    if not _contains_emoji(base):
        base = f"{base} {emoji}"
    return base.strip()


def _format_prize_items(items: list[dict], single_only: bool = True) -> str:
    """Convert structured prize list to readable text."""
    parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        prize_type = str(
            item.get("type")
            or item.get("name")
            or item.get("prize")
            or item.get("title")
            or ""
        ).strip()
        qty = item.get("quantity")
        if not prize_type:
            continue
        if isinstance(qty, int) and qty > 0:
            parts.append(f"{prize_type} ({qty} шт.)")
        else:
            parts.append(prize_type)
        if single_only and parts:
            break
    return ", ".join(parts).strip()


def _extract_single_prize_text(text: str) -> str:
    """Extract one prize from free-form text."""
    value = (text or "").strip()
    if not value:
        return ""

    # Prioritize first variant when alternatives are present.
    for sep in [" или ", " / ", "\n", ";", ","]:
        if sep in value:
            value = value.split(sep)[0].strip()
            break

    # Cleanup wrappers.
    value = value.strip(" -•")
    return value


def _normalize_prizes(prizes_value, brief: str = "", raw_response: str = "") -> str:
    """Normalize prizes into one plain readable string."""
    if isinstance(prizes_value, list):
        text = _format_prize_items(prizes_value, single_only=True)
        if text:
            return text
    elif isinstance(prizes_value, dict):
        text = _format_prize_items([prizes_value], single_only=True)
        if text:
            return text

    text = str(prizes_value or "").strip()
    if not text:
        combined = f"{brief}\n{raw_response}".lower()
        if "сертификат" in combined:
            return "Сертификат на 500 ₽ в компьютерный клуб"
        if "сувенир" in combined:
            return "Фирменные сувениры клуба"
        return "Подарки от организатора"

    # Try decode JSON/Python list string like:
    # [{'type': 'сертификат', 'quantity': 3}, ...]
    parsed = None
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except Exception:
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = None
    if isinstance(parsed, list):
        decoded = _format_prize_items(parsed, single_only=True)
        if decoded:
            return decoded

    return _extract_single_prize_text(text)


def _normalize_description(description: str, prizes: str) -> str:
    """Fix awkward wording and keep text concise."""
    text = str(description or "").strip()
    if not text:
        text = "Участвуйте в розыгрыше и получайте призы от клуба."

    # Replace awkward wording and raw data dumps.
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" или сувениры", " и сувениры")
    if any(token in text for token in ["[{", "{'", '["', '"]', "}]"]):
        text = ""

    if prizes and "разыграем" not in text.lower():
        text = f"Среди участников разыграем: {prizes}."
    return text


def _normalize_rules(rules: str) -> str:
    """Ensure rules are readable and structured."""
    text = str(rules or "").strip()
    if not text:
        return (
            "1) Подпишитесь на канал клуба.\n"
            "2) Нажмите кнопку участия под постом розыгрыша.\n"
            "3) Дождитесь публикации результатов."
        )
    if "1)" not in text and "2)" not in text:
        return (
            "1) Подпишитесь на канал клуба.\n"
            "2) Нажмите кнопку участия под постом розыгрыша.\n"
            "3) Дождитесь публикации результатов."
        )
    return text


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

    # Title: catchy compact 2-3 words with emoji.
    base_title = source.split(".")[0].split("\n")[0].strip()
    title = _normalize_title(base_title, brief=brief, raw_response=raw_response)

    # Simple prizes detection.
    combined = f"{brief}\n{raw_response}".lower()
    if "сертификат" in combined:
        prizes = "Сертификат на 500 ₽ в компьютерный клуб"
    elif "сувенир" in combined:
        prizes = "Фирменные сувениры клуба"
    else:
        prizes = "Подарок от организатора"

    description = (
        f"Среди участников разыграем: {prizes}."
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
            "prizes": _normalize_prizes(parsed.get("prizes", ""), brief=brief, raw_response=raw),
            "participation_rules": _normalize_rules(str(parsed.get("participation_rules", "")).strip()),
        }
        cleaned["title"] = _normalize_title(cleaned["title"], brief=brief, raw_response=raw)
        cleaned["description"] = _normalize_description(cleaned["description"], cleaned["prizes"])

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
            "Title must be 2-3 words in Russian and include emoji.",
            "Examples of title style: 'Осенняя лихорадка 🍁', 'Весенняя оттепель 🌸', 'Жаркий розыгрыш 🔥'.",
            "Use the same structure as manual mode fields:",
            "- title: short catchy name",
            "- description: one concise sentence about the giveaway",
            "- prizes: exactly ONE prize item, plain text string only",
            "- participation_rules: 3 short numbered lines",
            "Do not return arrays/objects in prizes. No [] {} in any field.",
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
