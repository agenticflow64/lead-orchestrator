"""Lead classification: LLM (OpenRouter -> GLM reserve) with regex-rules fallback.

Output contract (same shape from every provider):
    type:     price_question | support | complaint | partnership | spam | other
    urgency:  low | medium | high
    name / contact / summary: extracted fields, '' when absent (never invented)
"""

import json
import logging
import re
import time
from typing import Any, Callable

from .config import LEAD_TYPES, URGENCY_LEVELS
from .llm import chat_glm, chat_openrouter

log = logging.getLogger("leadorch.classifier")

SYSTEM_PROMPT = (
    "Ты — классификатор входящих заявок небольшой IT-компании. "
    "Ответь ТОЛЬКО валидным JSON без markdown и пояснений, все текстовые поля на русском:\n"
    '{"type": "price_question|support|complaint|partnership|spam|other", '
    '"urgency": "low|medium|high", "name": "", "contact": "", "summary": ""}\n'
    "Правила: type — категория заявки (вопрос о цене / техподдержка / жалоба / сотрудничество / "
    "спам / другое). Спам — навязчивая реклама и «замануха»: КАПС, $$$, обещания лёгкого заработка, "
    "«куплю/продам бизнес», «жми сюда», SEO-предложения — всё это spam, даже если написано по-русски "
    "с ошибками. urgency — low для вопросов без проблем, medium если что-то не работает но "
    "не критично, high при срочности, финансовых потерях, грубости или долгом отсутствии ответа; "
    "name — имя клиента если указано в тексте, иначе пустая строка (НЕ выдумывай); "
    "contact — телефон / email / telegram @username из текста, иначе пустая строка; "
    "summary — суть заявки одним предложением."
)


# ---------------------------------------------------------------------------
# Fallback rules (used when no LLM provider answers)
# ---------------------------------------------------------------------------

_TYPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("spam", re.compile(r"(купи|продам|заработок|выгода|\$\$\$|жми сюда|уникальное предложение|мест мало)", re.I)),
    ("partnership", re.compile(r"(сотрудничеств|партнёрств|партнерств|агентств|предлагаю.{0,30}баз)", re.I)),
    ("complaint", re.compile(r"(жалоб|нахамил|безобрази|требую|верните деньги|оставляет желать)", re.I)),
    ("price_question", re.compile(r"(сколько стоит|цена|цену|прайс|стоимость|бюджет)", re.I)),
    ("support", re.compile(r"(не работает|не открывает|ошибка|не приходит|не могу войти|не получается|сломал)", re.I)),
]

_HIGH_URGENCY = re.compile(r"(срочно|!!!|деньги списались|ошибка оплаты|не открывает|требую|нахамил|безобрази)", re.I)
_COMPLAINT_HIGH = re.compile(r"(требую|нахамил|безобрази|верните деньги)", re.I)

_NAME_STOPWORDS = {
    "здравствуйте", "добрый", "день", "что", "как", "уже", "ваш", "ваша", "прошу", "сайт", "ошибка",
    "нужно", "хотим", "мы", "я", "меня", "моя", "мой", "письмо", "аккаунт", "письма", "третью",
    "неделю", "жду", "ответа", "качество", "работы", "предлагаю", "партнерство", "партнёрство",
    "жалоба", "срочно", "спасибо", "пишите", "пишу",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+7|8)[\s(-]?\d{3}[\s)-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b|\b\d{3}[\s-]\d{3}[\s-]\d{2}[\s-]\d{2}\b")
_TG_RE = re.compile(r"@[A-Za-z0-9_]{4,}")
_WORD_RE = re.compile(r"[А-ЯЁ][а-яё]{2,}")
# something contact-like at the start of a string: phone, @username, email
_CONTACT_START_RE = re.compile(r"^(?:\+?\d|@|[A-Za-z0-9][A-Za-z0-9._%+-]*@)")


def _fallback_type(text: str) -> str:
    for type_, pattern in _TYPE_RULES:
        if pattern.search(text):
            return type_
    return "other"


def _fallback_urgency(text: str, type_: str) -> str:
    if type_ == "spam":
        return "low"  # spam never disturbs the on-call person
    if _HIGH_URGENCY.search(text):
        return "high"
    if type_ == "complaint":
        return "high" if _COMPLAINT_HIGH.search(text) else "medium"
    if type_ == "support":
        return "medium"
    return "low"


def _fallback_contact(text: str) -> str:
    for pattern in (_EMAIL_RE, _PHONE_RE, _TG_RE):
        m = pattern.search(text)
        if m:
            return m.group(0)
    return ""


def _fallback_name(text: str) -> str:
    """Signature-position heuristic: a capitalized word right before end-of-text, a comma
    or a contact token is treated as the client's name."""
    m = re.search(r"меня зовут\s+([А-ЯЁ][а-яё]+)", text, re.I)
    if m:
        return m.group(1)
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        if word.lower() in _NAME_STOPWORDS:
            continue
        rest = text[m.end() :].lstrip()
        if rest == "" or _CONTACT_START_RE.match(rest):
            return word  # "…бюджет. Дмитрий" / "Ольга +7 900 …"
        if rest.startswith(","):
            tail = rest[1:].lstrip()
            if _CONTACT_START_RE.match(tail):
                return word  # "Александр, a.petrov@company.ru"
            follow = re.match(r"[А-ЯЁ][а-яё]+", tail)
            if follow:
                return follow.group(0)  # "Жалоба, Сергей"
        # otherwise: word starts a normal sentence ("Сколько стоит…") — skip
    return ""


def _fallback_summary(text: str) -> str:
    m = re.search(r"[^.!?]*[.!?]", text)
    summary = (m.group(0) if m else text).strip()
    return summary[:140]


def classify_by_rules(text: str) -> dict[str, Any]:
    """Deterministic regex classification — last-resort provider and unit-test target."""
    type_ = _fallback_type(text)
    return {
        "type": type_ if type_ in LEAD_TYPES else "other",
        "urgency": _fallback_urgency(text, type_),
        "name": _fallback_name(text),
        "contact": _fallback_contact(text),
        "summary": _fallback_summary(text),
    }


# ---------------------------------------------------------------------------
# LLM classification with provider chain and retries
# ---------------------------------------------------------------------------


def _providers() -> list[tuple[str, Callable[[str, str], Any]]]:
    from .config import settings

    chain = []
    if settings.openrouter_enabled:
        chain.append(("openrouter", chat_openrouter))
    if settings.glm_enabled:
        chain.append(("glm", chat_glm))
    return chain


def _parse_llm_json(raw: str) -> dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in completion")
    data = json.loads(raw[start : end + 1])
    type_ = data.get("type", "other")
    urgency = data.get("urgency", "low")
    return {
        "type": type_ if type_ in LEAD_TYPES or type_ == "other" else "other",
        "urgency": urgency if urgency in URGENCY_LEVELS else "low",
        "name": str(data.get("name") or "").strip(),
        "contact": str(data.get("contact") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
    }


def classify(text: str, attempts_per_provider: int = 2) -> dict[str, Any]:
    """Classify a lead. Tries LLM providers in order, falls back to regex rules."""
    for label, fn in _providers():
        for attempt in range(1, attempts_per_provider + 1):
            t0 = time.monotonic()
            try:
                result = fn(SYSTEM_PROMPT, text)
                parsed = _parse_llm_json(result.content)
                parsed["provider"] = result.provider
                log.info("classified by %s in %.1fs (attempt %d)", result.provider, time.monotonic() - t0, attempt)
                return parsed
            except Exception as exc:  # noqa: BLE001 — any provider failure falls through
                log.warning("%s attempt %d failed: %s", label, attempt, exc)
                time.sleep(1.0)
    log.warning("all LLM providers failed, using regex rules")
    result = classify_by_rules(text)
    result["provider"] = "rules"
    return result
