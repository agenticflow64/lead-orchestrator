"""Application settings loaded from environment (.env is sourced by docker/compose or shell)."""

import os
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

LEAD_TYPES = ("price_question", "support", "complaint", "partnership", "spam")
URGENCY_LEVELS = ("low", "medium", "high")
STATUSES = ("new", "in_progress", "done")


@dataclass
class Settings:
    """All runtime knobs. Every integration degrades to a local mock when unset."""

    # LLM providers: OpenRouter free model first, GLM as reserve, regex rules as last resort.
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    openrouter_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    )
    glm_api_key: str = field(default_factory=lambda: os.getenv("GLM_API_KEY", ""))
    glm_model: str = field(default_factory=lambda: os.getenv("GLM_MODEL", "glm-4-flash"))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "45")))

    # Telegram: empty bot token switches both inbound confirmations and outbound
    # notifications to a local mock (log file + dashboard feed).
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # Storage: SQLite by default; Google Sheets slot is kept for the production variant.
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", os.path.join(BASE_DIR, "data", "leads.db")))
    notifications_log: str = field(
        default_factory=lambda: os.getenv("NOTIFICATIONS_LOG", os.path.join(BASE_DIR, "data", "notifications.log"))
    )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def openrouter_enabled(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def glm_enabled(self) -> bool:
        return bool(self.glm_api_key)


settings = Settings()
