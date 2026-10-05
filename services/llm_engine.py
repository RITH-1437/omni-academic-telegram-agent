import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import httpx

from config import settings
from config.prompts import (
    CODE_DEBUGGER_PROMPT,
    DOCUMENT_SUMMARY_PROMPT,
    REFACTOR_MESSAGE_PROMPT,
    TRANSLATE_PROMPT_ENGLISH,
    TRANSLATE_PROMPT_KHMER,
    get_system_prompt_for_course,
)

logger = logging.getLogger(__name__)


class LLMEngineError(Exception):
    """Raised when all configured LLM providers fail."""
    pass


@dataclass
class LLMProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    priority: int = 1
    timeout: float = 30.0
    extra_headers: Dict[str, str] = field(default_factory=dict)
    consecutive_errors: int = 0
    last_error_timestamp: float = 0.0

    @property
    def is_configured(self) -> bool:
        """Check if provider has a non-empty API key."""
        return bool(self.api_key and self.api_key.strip() and not self.api_key.startswith("your_"))

    def is_in_cooldown(self, cooldown_seconds: float = 30.0) -> bool:
        """Check if provider is temporarily cooled down due to repeated failures."""
        if self.consecutive_errors >= 3:
            if time.time() - self.last_error_timestamp < cooldown_seconds:
                return True
            # Cooldown expired, allow retry
            self.consecutive_errors = 1
        return False


class LLMEngine:
    """
    Multi-Provider Asynchronous LLM Engine.
    Executes an array of prioritized providers (OpenCode Zen, OpenRouter, etc.).
    Fastest / priority provider runs first; on any error or timeout, instantly
    falls back to the next available provider in the array.
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._providers: List[LLMProviderConfig] = []
        self._build_provider_array()

    def _build_provider_array(self) -> None:
        """Construct the prioritized array of LLM providers from settings."""
        # 1. OpenRouter Provider
        openrouter = LLMProviderConfig(
            name="openrouter",
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL.rstrip("/"),
            model=settings.OPENROUTER_MODEL,
            timeout=30.0,
            extra_headers={
                "HTTP-Referer": "https://github.com/Year5-TelegramBot",
                "X-Title": "Year 5 CS Academic Telegram Bot",
            },
        )

        # 2. OpenCode Zen Provider
        opencode_zen = LLMProviderConfig(
            name="opencode_zen",
            api_key=settings.OPENCODE_ZEN_API_KEY,
            base_url=settings.OPENCODE_ZEN_BASE_URL.rstrip("/"),
            model=settings.OPENCODE_ZEN_MODEL,
            timeout=30.0,
        )

        # 3. Direct Google Gemini Provider (Optional fallback)
        gemini = LLMProviderConfig(
            name="gemini",
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com",
            model=settings.GEMINI_MODEL,
            timeout=30.0,
        )

        registered_map = {
            "openrouter": openrouter,
            "opencode_zen": opencode_zen,
            "gemini": gemini,
        }

        # Parse user's priority order from settings (e.g. "opencode_zen,openrouter" or "openrouter,opencode_zen")
        raw_order = [p.strip().lower() for p in settings.LLM_PROVIDER_ORDER.split(",") if p.strip()]

        ordered_providers: List[LLMProviderConfig] = []
        for idx, provider_name in enumerate(raw_order):
            if provider_name in registered_map:
                prov = registered_map[provider_name]
                prov.priority = idx + 1
                ordered_providers.append(prov)

        # Append any configured providers not explicitly mentioned in the priority string
        for name, prov in registered_map.items():
            if prov not in ordered_providers and prov.is_configured:
                prov.priority = len(ordered_providers) + 1
                ordered_providers.append(prov)

        self._providers = ordered_providers

        # Log configured providers
        configured_names = [p.name for p in self._providers if p.is_configured]
        logger.info(
            "Initialized LLM Provider Array (Priority Order: %s | Configured: %s)",
            [p.name for p in self._providers],
            configured_names or "None! Please set keys in .env",
        )

    def get_http_client(self) -> httpx.AsyncClient:
        """Obtain or initialize shared persistent httpx.AsyncClient."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(45.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
            )
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client session."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def get_active_providers(self) -> List[LLMProviderConfig]:
        """
        Return the list of configured providers sorted by priority.
        Cooled-down providers are temporarily placed at the end of the array.
        """
        active = [p for p in self._providers if p.is_configured]
        # Sort so healthy priority providers come first, then cooled-down ones
        return sorted(active, key=lambda p: (1 if p.is_in_cooldown() else 0, p.priority))

    # --------------------------------------------------------------------------
    # Core Request Dispatcher with Fast Prioritized Failover
    # --------------------------------------------------------------------------

    async def generate_response(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.2,
    ) -> str:
        """
        Send prompt to the prioritized array of LLM providers.
        Executes the fastest/highest-priority provider first.
        If it encounters any rate-limit (429), auth error (401), timeout,
        or server error (5xx), it instantly fails over to the next provider.
        """
        active_providers = self.get_active_providers()
        if not active_providers:
            raise LLMEngineError(
                "No active LLM providers configured! Please set OPENROUTER_API_KEY or "
                "OPENCODE_ZEN_API_KEY (or GEMINI_API_KEY) in your .env file."
            )

        errors: List[str] = []

        for provider in active_providers:
            start_time = time.time()
            try:
                logger.info(
                    "Dispatching request to Provider [%s] (model: %s, priority: %d)...",
                    provider.name,
                    provider.model,
                    provider.priority,
                )

                if provider.name in ("openrouter", "opencode_zen"):
                    result = await self._call_openai_compatible(
                        provider=provider,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                    )
                elif provider.name == "gemini":
                    result = await self._call_gemini(
                        provider=provider,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                    )
                else:
                    # Generic OpenAI-compatible fallback
                    result = await self._call_openai_compatible(
                        provider=provider,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=temperature,
                    )

                # Success: reset error state and return immediately
                elapsed = time.time() - start_time
                provider.consecutive_errors = 0
                logger.info(
                    "Provider [%s] responded successfully in %.2fs!",
                    provider.name,
                    elapsed,
                )
                return result

            except Exception as e:
                elapsed = time.time() - start_time
                provider.consecutive_errors += 1
                provider.last_error_timestamp = time.time()
                error_msg = f"Provider [{provider.name}] failed after {elapsed:.2f}s: {e}"
                logger.warning("%s. Failing over to next provider in array...", error_msg)
                errors.append(error_msg)

        all_err_summary = "\n".join(errors)
        logger.error("All providers in array failed:\n%s", all_err_summary)
        raise LLMEngineError(
            f"All configured LLM providers failed to respond:\n{all_err_summary}"
        )

    # --------------------------------------------------------------------------
    # Provider-Specific Call Implementations
    # --------------------------------------------------------------------------

    async def _call_openai_compatible(
        self,
        provider: LLMProviderConfig,
        prompt: str,
        system_instruction: str,
        temperature: float,
    ) -> str:
        """Call standard OpenAI-compatible /chat/completions endpoint (OpenRouter, OpenCode Zen)."""
        client = self.get_http_client()
        url = f"{provider.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            **provider.extra_headers,
        }

        payload: Dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }

        # For OpenRouter, use the 'models' array to enable automatic upstream failover
        if provider.name == "openrouter":
            models_list = [m.strip() for m in provider.model.split(",") if m.strip()]
            if any(":free" in m for m in models_list):
                for fallback in ["liquid/lfm-2.5-2.6b:free", "qwen/qwen3.8-27b:free", "google/gemma-4-26b-a4b-it:free"]:
                    if fallback not in models_list:
                        models_list.append(fallback)
            payload["models"] = models_list
        else:
            payload["model"] = provider.model

        # Retry once or twice if upstream returns 429 rate limit
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            response = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=provider.timeout,
            )

            if response.status_code == 429 and attempt < max_attempts:
                logger.info(
                    "Provider [%s] hit rate limit (429). Retrying in 1.5s (attempt %d/%d)...",
                    provider.name,
                    attempt,
                    max_attempts,
                )
                await asyncio.sleep(1.5)
                continue

            if response.status_code != 200:
                err_body = response.text[:400]
                raise RuntimeError(
                    f"HTTP {response.status_code} from {provider.name}: {err_body}"
                )
            break

        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise RuntimeError(f"Malformed response format from {provider.name}: {data}")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not content:
            raise RuntimeError(f"Empty content returned by {provider.name}")

        return content.strip()

    async def _call_gemini(
        self,
        provider: LLMProviderConfig,
        prompt: str,
        system_instruction: str,
        temperature: float,
    ) -> str:
        """Call Google Gemini as an optional fallback provider."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=provider.api_key)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
        )
        response = await client.aio.models.generate_content(
            model=provider.model,
            contents=prompt,
            config=config,
        )
        if response and response.text:
            return response.text.strip()
        raise RuntimeError("Empty response from Google Gemini")

    # --------------------------------------------------------------------------
    # Specialized Academic Workflows
    # --------------------------------------------------------------------------

    async def summarize_document(
        self,
        document_text: str,
        course_key: str,
        metadata: dict,
    ) -> str:
        """Summarize extracted document content with domain course context."""
        course_prompt = get_system_prompt_for_course(course_key)
        system_instruction = (
            f"{course_prompt}\n\n"
            f"TASK INSTRUCTION:\n{DOCUMENT_SUMMARY_PROMPT}"
        )
        meta_info = (
            f"[Document Info: {metadata.get('filename', 'Unknown')} | "
            f"Type: {metadata.get('type', 'Doc')} | "
            f"Length: {metadata.get('total_characters', len(document_text))} chars]\n\n"
        )
        user_prompt = f"{meta_info}DOCUMENT CONTENT:\n\n{document_text}"
        return await self.generate_response(user_prompt, system_instruction, temperature=0.2)

    async def translate_text(
        self,
        text: str,
        target_lang: str = "kh",
    ) -> str:
        """
        Translate technical content into academic Khmer or polished English,
        strictly maintaining IT/CS technical terms.
        """
        if target_lang.lower() in ("kh", "khmer", "cambodia"):
            system_instruction = TRANSLATE_PROMPT_KHMER
            user_prompt = f"Please translate the following technical academic text into formal Academic Khmer:\n\n{text}"
        else:
            system_instruction = TRANSLATE_PROMPT_ENGLISH
            user_prompt = f"Please polish and refine the following text into formal Academic English:\n\n{text}"

        return await self.generate_response(user_prompt, system_instruction, temperature=0.2)

    async def refactor_message(
        self,
        raw_message: str,
        course_key: str,
    ) -> str:
        """Polish and elevate student messages for professors, peers, and presentations."""
        course_prompt = get_system_prompt_for_course(course_key)
        system_instruction = (
            f"{course_prompt}\n\n"
            f"COMMUNICATION COACH INSTRUCTION:\n{REFACTOR_MESSAGE_PROMPT}"
        )
        user_prompt = f"Please polish the following student message into the 3 specified academic styles:\n\n{raw_message}"
        return await self.generate_response(user_prompt, system_instruction, temperature=0.3)

    async def debug_code_or_problem(
        self,
        code_snippet: str,
        course_key: str,
    ) -> str:
        """Analyze and debug code snippets, runtime traces, and algorithmic bugs."""
        course_prompt = get_system_prompt_for_course(course_key)
        system_instruction = (
            f"{course_prompt}\n\n"
            f"DEBUGGER INSTRUCTION:\n{CODE_DEBUGGER_PROMPT}"
        )
        user_prompt = f"Please analyze and resolve this code / error / problem in depth:\n\n{code_snippet}"
        return await self.generate_response(user_prompt, system_instruction, temperature=0.1)

    async def answer_academic_query(
        self,
        question: str,
        course_key: str,
    ) -> str:
        """Answer a student's general or subject-specific academic question."""
        course_prompt = get_system_prompt_for_course(course_key)
        system_instruction = (
            f"{course_prompt}\n\n"
            "Answer the student's question clearly, thoroughly, and academically. "
            "Use clear headings, formatted equations, or cleanly commented code when helpful."
        )
        return await self.generate_response(question, system_instruction, temperature=0.3)


llm_engine = LLMEngine()
