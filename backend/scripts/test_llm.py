"""Smoke-test the configured LLM runtime path."""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

env_path = REPO_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)

from app.ai.llm_client import get_llm_client, get_llm_status, reset_client
from app.config import settings


async def main() -> int:
    """Run a minimal prompt through the configured app client."""
    reset_client()

    print("Testing configured LLM runtime...")
    print(f"Configured provider: {settings.llm_provider}")
    if settings.llm_provider == "custom":
        print(f"Custom API format: {settings.custom_api_format}")

    client = get_llm_client()
    status = get_llm_status()

    print(f"Active provider: {status['provider']}")
    print(f"Model: {getattr(client, 'model', 'unknown')}")

    if status["is_degraded"]:
        print(f"✗ Degraded: {status['degradation_reason']}")
        return 1

    try:
        response = await client.generate("Say 'hello Hawy' if you can read this.")
    except Exception as exc:
        print(f"✗ Failed: {exc}")
        return 1

    print("✓ Success!")
    print(f"Response: {response}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
