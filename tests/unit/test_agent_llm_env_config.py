"""仓库根 .env 多供应商配置验收.

契约：
- ``_load_llm_env`` 只读解析仓库根 ``.env``（KEY=VALUE、``#`` 注释、
  前后空格、单/双引号剥离；缺文件返回 ``{}``，永不新建/写入）；
- 只认 ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` / ``BRW_LLM_MODEL``
  三个变量名，其它变量一律拒绝（不进入结果，不抛错——``.env`` 是
  全仓库共享空间，数据库等变量与本模块无关）；
- ``_llm_env_snapshot`` 合并显式环境变量与文件值：显式环境优先，
  空字符串视为未设置（回退文件值，兼容 compose ``${VAR:-}`` 空串透传）。
"""

from __future__ import annotations

import sys
import types


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


class TestLoadLlmEnv:
    def test_parses_key_base_url_model(self, tmp_path, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        env = tmp_path / ".env"
        env.write_text(
            "# LLM 网关配置\n"
            "OPENAI_API_KEY=sk-deepseek-test\n"
            "OPENAI_BASE_URL=https://api.deepseek.com\n"
            "BRW_LLM_MODEL=deepseek-chat\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        data = U._load_llm_env()
        assert data == {
            "OPENAI_API_KEY": "sk-deepseek-test",
            "OPENAI_BASE_URL": "https://api.deepseek.com",
            "BRW_LLM_MODEL": "deepseek-chat",
        }

    def test_comments_spaces_quotes(self, tmp_path):
        from battery_workbench.agent_assistant import understanding as U

        env = tmp_path / ".env"
        env.write_text(
            "  # 前导空格注释\n"
            "  OPENAI_API_KEY =  sk-test  \n"
            'OPENAI_BASE_URL="https://custom.gateway/v1"\n'
            "BRW_LLM_MODEL='my-model'\n"
            "MALFORMED_LINE_WITHOUT_EQUALS\n"
            "\n",
            encoding="utf-8",
        )
        data = U._load_llm_env(env)
        assert data["OPENAI_API_KEY"] == "sk-test"
        assert data["OPENAI_BASE_URL"] == "https://custom.gateway/v1"
        assert data["BRW_LLM_MODEL"] == "my-model"

    def test_missing_file_returns_empty(self, tmp_path):
        from battery_workbench.agent_assistant import understanding as U

        data = U._load_llm_env(tmp_path / ".env")
        assert data == {}

    def test_unknown_names_rejected(self, tmp_path):
        from battery_workbench.agent_assistant import understanding as U

        env = tmp_path / ".env"
        env.write_text(
            "BRW_DATABASE_URL=sqlite:///./brw.db\n"
            "OPENAI_API_KEY=sk-test\n"
            "OPENAI_API_ORG=org-should-not-pass\n"
            "EVIL_INJECTED=yes\n",
            encoding="utf-8",
        )
        data = U._load_llm_env(env)
        assert data == {"OPENAI_API_KEY": "sk-test"}


class TestLlmEnvSnapshot:
    def test_explicit_env_wins_over_file(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        monkeypatch.setattr(
            U,
            "_load_llm_env",
            lambda *a, **k: {
                "OPENAI_API_KEY": "file-key",
                "OPENAI_BASE_URL": "https://file.gateway",
                "BRW_LLM_MODEL": "file-model",
            },
        )
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("BRW_LLM_MODEL", raising=False)

        snap = U._llm_env_snapshot()
        assert snap["OPENAI_API_KEY"] == "env-key"
        assert snap["OPENAI_BASE_URL"] == "https://file.gateway"
        assert snap["BRW_LLM_MODEL"] == "file-model"

    def test_empty_env_falls_back_to_file(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        monkeypatch.setattr(
            U,
            "_load_llm_env",
            lambda *a, **k: {"OPENAI_BASE_URL": "https://file.gateway"},
        )
        # compose ${VAR:-} 缺省时透传空字符串，必须视为未设置
        monkeypatch.setenv("OPENAI_BASE_URL", "")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        snap = U._llm_env_snapshot()
        assert snap["OPENAI_BASE_URL"] == "https://file.gateway"
        assert "OPENAI_API_KEY" not in snap

    def test_call_llm_uses_file_values(self, monkeypatch):
        from battery_workbench.agent_assistant import understanding as U

        recorder: dict = {}
        _install_fake_openai(monkeypatch, recorder)
        monkeypatch.setattr(
            U,
            "_load_llm_env",
            lambda *a, **k: {
                "OPENAI_API_KEY": "file-key",
                "OPENAI_BASE_URL": "https://api.deepseek.com",
                "BRW_LLM_MODEL": "deepseek-chat",
            },
        )
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("BRW_LLM_MODEL", raising=False)

        data = U._call_llm("帮我研究SOC")

        assert data["intent"] == "SELECT_TARGET"
        assert recorder["ctor"]["api_key"] == "file-key"
        assert recorder["ctor"]["base_url"] == "https://api.deepseek.com"
        assert recorder["create"]["model"] == "deepseek-chat"
