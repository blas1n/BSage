"""Tests for bsage.core.danger_analyzer — StaticAnalyzer, DangerCache, DangerAnalyzer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bsage.core.danger_analyzer import DangerAnalyzer, DangerCache, StaticAnalyzer


class TestStaticAnalyzer:
    """Test AST-based dangerous import detection."""

    @pytest.fixture()
    def analyzer(self) -> StaticAnalyzer:
        return StaticAnalyzer()

    def test_detects_requests_import(self, analyzer: StaticAnalyzer) -> None:
        code = "import requests\n\nasync def execute(context):\n    requests.get('http://x')\n"
        result = analyzer.analyze(code)
        assert result is not None
        is_dangerous, reason = result
        assert is_dangerous is True
        assert "requests" in reason

    def test_detects_httpx_import(self, analyzer: StaticAnalyzer) -> None:
        code = "import httpx\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True

    def test_detects_aiohttp_import(self, analyzer: StaticAnalyzer) -> None:
        code = "import aiohttp\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True

    def test_detects_subprocess_import(self, analyzer: StaticAnalyzer) -> None:
        code = "import subprocess\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True

    def test_detects_smtplib_import(self, analyzer: StaticAnalyzer) -> None:
        code = "import smtplib\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True

    def test_detects_from_import(self, analyzer: StaticAnalyzer) -> None:
        code = "from httpx import AsyncClient\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True
        assert "httpx" in result[1]

    def test_detects_urllib_from_import(self, analyzer: StaticAnalyzer) -> None:
        code = "from urllib.request import urlopen\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True

    def test_safe_vault_only_code(self, analyzer: StaticAnalyzer) -> None:
        code = (
            "async def execute(context):\n"
            "    data = context.input_data\n"
            "    await context.garden.write_seed('test', data)\n"
            "    return {'ok': True}\n"
        )
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is False
        assert "No dangerous" in result[1]

    def test_safe_standard_library_imports(self, analyzer: StaticAnalyzer) -> None:
        code = (
            "import json\n"
            "import re\n"
            "from datetime import datetime\n"
            "async def execute(context):\n"
            "    return {}\n"
        )
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is False

    def test_returns_none_on_syntax_error(self, analyzer: StaticAnalyzer) -> None:
        code = "def broken(:\n    pass\n"
        result = analyzer.analyze(code)
        assert result is None

    def test_multiple_dangerous_imports_listed(self, analyzer: StaticAnalyzer) -> None:
        code = "import requests\nimport smtplib\n\nasync def execute(context):\n    pass\n"
        result = analyzer.analyze(code)
        assert result is not None
        assert result[0] is True
        assert "requests" in result[1]
        assert "smtplib" in result[1]


class TestDangerCache:
    """Test JSON-backed cache with content hash invalidation."""

    @pytest.fixture()
    def cache(self, tmp_path: Path) -> DangerCache:
        return DangerCache(tmp_path / "danger.json")

    def test_get_returns_none_on_miss(self, cache: DangerCache) -> None:
        result = cache.get("my-plugin", "some code")
        assert result is None

    def test_set_and_get_hit(self, cache: DangerCache) -> None:
        cache.set("my-plugin", "some code", (True, "external calls"))
        result = cache.get("my-plugin", "some code")
        assert result == (True, "external calls")

    def test_get_returns_none_on_hash_mismatch(self, cache: DangerCache) -> None:
        cache.set("my-plugin", "code v1", (False, "safe"))
        result = cache.get("my-plugin", "code v2 changed")
        assert result is None

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "danger.json"
        cache1 = DangerCache(cache_path)
        cache1.set("plugin-x", "content", (True, "dangerous"))

        cache2 = DangerCache(cache_path)
        result = cache2.get("plugin-x", "content")
        assert result == (True, "dangerous")

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        cache = DangerCache(tmp_path / "sub" / "dir" / "cache.json")
        cache.set("p", "code", (False, "safe"))
        assert (tmp_path / "sub" / "dir" / "cache.json").exists()

    def test_handles_corrupt_cache_file(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "danger.json"
        cache_path.write_text("not valid json", encoding="utf-8")
        cache = DangerCache(cache_path)
        assert cache.get("anything", "code") is None


class TestDangerAnalyzer:
    """Test DangerAnalyzer orchestration: cache → static → LLM."""

    @pytest.fixture()
    def cache_path(self, tmp_path: Path) -> Path:
        return tmp_path / "danger.json"

    async def test_static_detects_dangerous_import(self, cache_path: Path) -> None:
        analyzer = DangerAnalyzer(cache_path)
        code = "import requests\nasync def execute(context):\n    pass\n"
        is_dangerous, reason = await analyzer.analyze("p", code, "desc")
        assert is_dangerous is True
        assert "requests" in reason

    async def test_static_marks_safe_code(self, cache_path: Path) -> None:
        analyzer = DangerAnalyzer(cache_path)
        code = "async def execute(context):\n    return {}\n"
        is_dangerous, _ = await analyzer.analyze("p", code, "desc")
        assert is_dangerous is False

    async def test_cache_hit_skips_analysis(self, cache_path: Path) -> None:
        llm_fn = AsyncMock(return_value='{"is_dangerous": false, "reason": "safe"}')
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        code = "async def execute(context):\n    return {}\n"

        # First call
        await analyzer.analyze("p", code, "desc")
        # Second call — should use cache
        result = await analyzer.analyze("p", code, "desc")

        assert result[0] is False
        llm_fn.assert_not_called()

    async def test_cache_invalidated_on_content_change(self, cache_path: Path) -> None:
        analyzer = DangerAnalyzer(cache_path)
        code_v1 = "async def execute(context):\n    return {}\n"
        code_v2 = "import requests\nasync def execute(context):\n    pass\n"

        result_v1 = await analyzer.analyze("p", code_v1, "desc")
        result_v2 = await analyzer.analyze("p", code_v2, "desc")

        assert result_v1[0] is False
        assert result_v2[0] is True

    async def test_llm_fallback_on_ast_failure(self, cache_path: Path) -> None:
        llm_fn = AsyncMock(return_value='{"is_dangerous": true, "reason": "calls external API"}')
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        broken_code = "def broken(:\n    pass\n"

        is_dangerous, reason = await analyzer.analyze("p", broken_code, "desc")

        assert is_dangerous is True
        assert "external API" in reason
        llm_fn.assert_called_once()

    async def test_no_llm_ast_failure_defaults_dangerous(self, cache_path: Path) -> None:
        analyzer = DangerAnalyzer(cache_path, llm_fn=None)
        broken_code = "def broken(:\n    pass\n"

        is_dangerous, reason = await analyzer.analyze("p", broken_code, "desc")

        assert is_dangerous is True
        assert "defaulting to dangerous" in reason

    async def test_llm_json_parse_failure_defaults_dangerous(self, cache_path: Path) -> None:
        llm_fn = AsyncMock(return_value="not valid json at all")
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        broken_code = "def broken(:\n    pass\n"

        is_dangerous, _ = await analyzer.analyze("p", broken_code, "desc")

        assert is_dangerous is True

    async def test_llm_response_strips_markdown_fence(self, cache_path: Path) -> None:
        llm_fn = AsyncMock(return_value='```json\n{"is_dangerous": false, "reason": "safe"}\n```')
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        broken_code = "def broken(:\n    pass\n"

        is_dangerous, reason = await analyzer.analyze("p", broken_code, "desc")

        assert is_dangerous is False
        assert reason == "safe"

    async def test_result_written_to_cache(self, cache_path: Path) -> None:
        analyzer = DangerAnalyzer(cache_path)
        code = "async def execute(context):\n    return {}\n"
        await analyzer.analyze("p", code, "desc")

        data = json.loads(cache_path.read_text())
        assert "p" in data
        assert data["p"]["is_dangerous"] is False
