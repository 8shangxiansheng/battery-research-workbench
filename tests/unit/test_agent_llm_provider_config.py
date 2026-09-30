"""LLM provider 配置验收（DeepSeek / OpenAI 兼容接口）.

契约：
- ``_call_llm`` 必须把 ``OPENAI_BASE_URL`` 透传给 ``OpenAI`` client，
  无配置时为 ``None``（走官方默认地址）；
- ``BRW_LLM_MODEL`` 决定请求模型名；
- 无 key 时 ``_llm_available`` 为 False，``_call_llm`` 直接抛错
  （上游 ``understand`` 捕获并确定性回退）。
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_fake_openai(monkeypatch, recorder):
    """注入无第三方依赖的 fake openai 模块，记录 client 构造与请求参数."""

    class _FakeMessage:
        def __init__(self, content):
            self.content = content

    class _FakeChoice:
        def __init__(self, content):
            self.message = _FakeMessage(content)

    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]

    class _FakeCompletions:
        def create(self, **kwargs):
            recorder["create"] = kwargs
            return _FakeResp(
                '{"intent": "SELECT_TARGET", '
                '"target_id": "reference_soc_percent", '
                '"features": ["SWA"]}'
            )

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            recorder["ctor"] = kwargs
            self.chat = _FakeChat()

    mod = types.ModuleType("openai")
    mod.OpenAI = _FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)


@pytest.fixture(autouse=True)
def _isolate_llm_env_file(monkeypatch):
    """隔离仓库根 ``.env``：本文件只断言显式环境变量行为."""
    from battery_workbench.agent_assistant import understanding as U

    monkeypatch.setattr(U, "_load_llm_env", lambda *a, **k: {})


class TestLLMProviderConfig:
    def test_base_url_passed_to_client(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        recorder: dict = {}
        _install_fake_openai(monkeypatch, recorder)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("BRW_LLM_MODEL", "deepseek-chat")

        data = U._call_llm("帮我研究SOC")

        assert data["intent"] == "SELECT_TARGET"
        assert recorder["ctor"]["base_url"] == "https://api.deepseek.com"
        assert recorder["create"]["model"] == "deepseek-chat"

    def test_no_base_url_defaults_to_none(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        recorder: dict = {}
        _install_fake_openai(monkeypatch, recorder)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("BRW_LLM_MODEL", raising=False)

        U._call_llm("帮我研究SOC")

        assert recorder["ctor"].get("base_url") is None
        assert recorder["create"]["model"] == "gpt-4o-mini"

    def test_empty_base_url_normalized_to_none(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        recorder: dict = {}
        _install_fake_openai(monkeypatch, recorder)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        # docker-compose ${VAR:-} 未设置时透传空字符串，必须归一为 None
        monkeypatch.setenv("OPENAI_BASE_URL", "")

        U._call_llm("帮我研究SOC")

        assert recorder["ctor"].get("base_url") is None

    def test_unavailable_without_key(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert U._llm_available() is False
