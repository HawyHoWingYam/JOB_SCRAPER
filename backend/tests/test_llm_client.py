import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.llm_client import AnthropicClient


class FakeMessages:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="internal reasoning"),
                SimpleNamespace(type="text", text="hello Hawy"),
            ]
        )


class FakeAnthropicSdk:
    messages = FakeMessages()


@pytest.mark.asyncio
async def test_anthropic_generate_skips_non_text_blocks_before_text():
    client = AnthropicClient("test-key", "test-model")
    client._get_client = lambda: FakeAnthropicSdk()

    result = await client.generate("Say hello")

    assert result == "hello Hawy"
