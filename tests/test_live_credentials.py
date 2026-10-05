import asyncio
import os
import sys
import time

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import settings
from services import llm_engine
from telegram import Bot


async def test_telegram_token():
    print("\n--- 1. Testing Telegram Bot Token ---")
    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        me = await bot.get_me()
        print(f"✅ Telegram Token Valid! Bot Username: @{me.username} (ID: {me.id})")
        return True
    except Exception as e:
        print(f"❌ Telegram Token Error: {e}")
        return False


async def test_llm_providers():
    print("\n--- 2. Testing Prioritized LLM Provider Array ---")
    active_providers = [p for p in llm_engine._providers if p.is_configured]

    if not active_providers:
        print("⚠️ No LLM API keys configured! Please set OPENROUTER_API_KEY or OPENCODE_ZEN_API_KEY in .env")
        return False

    print(f"Configured Priority Order: {[p.name for p in active_providers]}")
    all_ok = True

    for p in active_providers:
        print(f"\nTesting Provider: [{p.name}] (Model: {p.model}, Base URL: {p.base_url})...")
        t0 = time.time()
        try:
            if p.name in ("openrouter", "opencode_zen"):
                resp = await llm_engine._call_openai_compatible(
                    provider=p,
                    prompt="Reply with exactly: 'OK'",
                    system_instruction="Be concise.",
                    temperature=0.0,
                )
            else:
                resp = await llm_engine._call_gemini(
                    provider=p,
                    prompt="Reply with exactly: 'OK'",
                    system_instruction="Be concise.",
                    temperature=0.0,
                )
            elapsed = time.time() - t0
            print(f"✅ [{p.name}] Success! Responded in {elapsed:.2f}s: {resp}")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"❌ [{p.name}] Failed after {elapsed:.2f}s: {e}")
            all_ok = False

    # Test integrated dispatch with failover
    print("\n--- 3. Testing High-Level Engine Dispatch (Priority + Failover) ---")
    try:
        t0 = time.time()
        resp = await llm_engine.generate_response(
            prompt="Reply with: 'Engine Ready'",
            system_instruction="You are an academic bot.",
            temperature=0.0,
        )
        elapsed = time.time() - t0
        print(f"✅ LLM Engine Dispatch Success in {elapsed:.2f}s: {resp}")
        return True
    except Exception as e:
        print(f"❌ LLM Engine Dispatch Error: {e}")
        return False


async def main():
    print("========================================")
    print(" Running Live API Credentials Test")
    print("========================================")
    tg_ok = await test_telegram_token()
    llm_ok = await test_llm_providers()
    print("\n========================================")
    if tg_ok and llm_ok:
        print("🎉 ALL SYSTEMS READY AND VERIFIED!")
    elif tg_ok and not llm_ok:
        print("⚠️ Telegram token is good, but configure your OpenRouter / OpenCode Zen key in .env!")
    else:
        print("⚠️ Some credentials failed. Please check your .env file.")
    print("========================================")


if __name__ == "__main__":
    asyncio.run(main())
