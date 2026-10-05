from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


@dataclass(frozen=True)
class CourseInfo:
    key: str
    name: str
    code: str
    icon: str
    description: str


COURSES: Dict[str, CourseInfo] = {
    "AI": CourseInfo(
        key="AI",
        name="Artificial Intelligence",
        code="CS501",
        icon="🤖",
        description="Search algorithms, heuristic optimization, adversarial search, MDPs, reinforcement learning, and neural network foundations.",
    ),
    "CLOUD": CourseInfo(
        key="CLOUD",
        name="Cloud Computing",
        code="CS502",
        icon="☁️",
        description="Distributed cloud systems, AWS/GCP architecture, VPC, IAM, Docker containers, Kubernetes orchestration, and serverless compute.",
    ),
    "DATA_MINING": CourseInfo(
        key="DATA_MINING",
        name="Data Mining",
        code="CS503",
        icon="⛏️",
        description="CRISP-DM methodology, data warehousing, association rule mining (Apriori/FP-Growth), clustering (K-Means/DBSCAN), and classification.",
    ),
    "IMAGE_PROC": CourseInfo(
        key="IMAGE_PROC",
        name="Image Processing",
        code="CS504",
        icon="🖼️",
        description="Digital image fundamentals, spatial & frequency filtering, Fourier transforms, edge detection (Sobel/Canny), morphological operations, and OpenCV.",
    ),
    "INFO_SEC": CourseInfo(
        key="INFO_SEC",
        name="Information Security",
        code="CS505",
        icon="🛡️",
        description="Cryptography primitives (AES, RSA, ECC, SHA-256), PKI/X.509 certificates, digital signatures, CIA triad, access controls, and security policies.",
    ),
    "NET_SEC": CourseInfo(
        key="NET_SEC",
        name="Network Security",
        code="CS506",
        icon="🔒",
        description="OSI/TCP-IP security, firewall architectures, IDS/IPS rules, WireGuard/IPsec VPNs, TLS 1.3 handshakes, Wireshark packet dissection, and attack mitigation.",
    ),
    "NLP": CourseInfo(
        key="NLP",
        name="Natural Language Processing",
        code="CS507",
        icon="🗣️",
        description="Text preprocessing, tokenization, n-grams, word embeddings (Word2Vec/GloVe), sequence models, Transformers (Self-Attention, BERT, GPT), and LLM architectures.",
    ),
    "IT_PM": CourseInfo(
        key="IT_PM",
        name="IT Project Management",
        code="CS508",
        icon="📊",
        description="Agile/Scrum framework, sprint planning, backlog grooming, Gantt/CPM scheduling, risk registers, COCOMO II cost estimation, and stakeholder communication.",
    ),
    "GENERAL": CourseInfo(
        key="GENERAL",
        name="General & Administrative",
        code="GEN500",
        icon="🏛️",
        description="Semester administrative notices, exam schedules, academic policies, university announcements, and cross-course coordination.",
    ),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core Credentials
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Telegram Bot API Token")

    # LLM Providers Configuration (Array priority: first active provider is used first)
    LLM_PROVIDER_ORDER: str = Field(
        default="openrouter,opencode_zen",
        description="Comma-separated priority order of LLM providers (e.g. openrouter,opencode_zen or opencode_zen,openrouter)",
    )

    # 1. OpenRouter
    OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API Key (sk-or-v1-...)")
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1", description="OpenRouter API Base URL")
    OPENROUTER_MODEL: str = Field(default="google/gemini-2.5-flash", description="OpenRouter Model Identifier")

    # 2. OpenCode Zen
    OPENCODE_ZEN_API_KEY: str = Field(default="", description="OpenCode Zen API Key")
    OPENCODE_ZEN_BASE_URL: str = Field(default="https://api.opencodezen.com/v1", description="OpenCode Zen API Base URL")
    OPENCODE_ZEN_MODEL: str = Field(default="gpt-4o-mini", description="OpenCode Zen Model Identifier")

    # 3. Direct Google Gemini (Optional fallback)
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash", description="Gemini Model Identifier")

    # Storage & Runtime
    DATABASE_PATH: str = Field(default="data/bot.db", description="Path to SQLite database")
    TIMEZONE: str = Field(default="Asia/Phnom_Penh", description="Local Timezone")
    RATE_LIMIT_REQUESTS: int = Field(default=10, description="Max LLM requests per window per user")
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, description="Rate limit sliding window in seconds")
    MAX_FILE_SIZE_BYTES: int = Field(default=20 * 1024 * 1024, description="Max document upload size (20MB)")

    # Static Topic Thread IDs (Optional: leave 0 if using dynamic DB mapping or general)
    TOPIC_THREAD_AI: int = 0
    TOPIC_THREAD_CLOUD: int = 0
    TOPIC_THREAD_DATA_MINING: int = 0
    TOPIC_THREAD_IMAGE_PROC: int = 0
    TOPIC_THREAD_INFO_SEC: int = 0
    TOPIC_THREAD_NET_SEC: int = 0
    TOPIC_THREAD_NLP: int = 0
    TOPIC_THREAD_IT_PM: int = 0
    TOPIC_THREAD_GENERAL: int = 0

    # Privileged User IDs
    ADMIN_USER_IDS: str = Field(default="", description="Comma-separated Telegram user IDs")

    def get_admin_ids(self) -> List[int]:
        """Parse comma-separated admin user IDs."""
        if not self.ADMIN_USER_IDS.strip():
            return []
        ids: List[int] = []
        for raw in self.ADMIN_USER_IDS.split(","):
            cleaned = raw.strip()
            if cleaned.isdigit():
                ids.append(int(cleaned))
        return ids

    def get_course_by_thread_id(self, thread_id: Optional[int]) -> CourseInfo:
        """Resolve CourseInfo based on static thread ID configuration."""
        if thread_id is None or thread_id == 0 or thread_id == 1:
            return COURSES["GENERAL"]

        mapping = {
            self.TOPIC_THREAD_AI: "AI",
            self.TOPIC_THREAD_CLOUD: "CLOUD",
            self.TOPIC_THREAD_DATA_MINING: "DATA_MINING",
            self.TOPIC_THREAD_IMAGE_PROC: "IMAGE_PROC",
            self.TOPIC_THREAD_INFO_SEC: "INFO_SEC",
            self.TOPIC_THREAD_NET_SEC: "NET_SEC",
            self.TOPIC_THREAD_NLP: "NLP",
            self.TOPIC_THREAD_IT_PM: "IT_PM",
            self.TOPIC_THREAD_GENERAL: "GENERAL",
        }

        # Check if thread_id matches any registered non-zero thread
        if thread_id in mapping and thread_id != 0:
            course_key = mapping[thread_id]
            return COURSES[course_key]

        return COURSES["GENERAL"]


settings = Settings()
