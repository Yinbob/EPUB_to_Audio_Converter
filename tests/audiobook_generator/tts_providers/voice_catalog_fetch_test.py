"""独立英文音色抓取脚本的离线测试。"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import requests

from audiobook_generator.tts_providers import voice_catalog
from audiobook_generator.tts_providers import voice_catalog_fetch as fetcher


MIMO_VOICE_TABLE = """
<html><body>
<table>
  <thead>
    <tr><th>Voice Name</th><th>Voice ID</th><th>Language</th><th>Gender</th></tr>
  </thead>
  <tbody>
    <tr><td>Mia</td><td>Mia</td><td>English</td><td>Female</td></tr>
    <tr><td>Chloe</td><td>Chloe</td><td>English</td><td>Female</td></tr>
    <tr><td>Milo</td><td>Milo</td><td>English</td><td>Male</td></tr>
    <tr><td>Dean</td><td>Dean</td><td>English</td><td>Male</td></tr>
    <tr><td>Default</td><td>mimo_default</td><td>Chinese</td><td>Neutral</td></tr>
    <tr><td>Chinese Voice</td><td>ChineseVoice</td><td>Chinese</td><td>Female</td></tr>
  </tbody>
</table>
</body></html>
"""

MIMO_SHELL = """
<html><head>
  <script src="/static/other.11111111.chunk.js"></script>
  <script src="/static/main.22222222.chunk.js"></script>
  <script>self.__dynamic={4833:"e7428a0684ae3437",7936:"2f58e6f67517ad94"};</script>
</head></html>
"""

MIMO_MAIN_JS = r'''
const routes = [
  {path:"zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5",importFn:()=>Promise.all([i.e(2374),i.e(7936)])},
  {path:"en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5",importFn:()=>Promise.all([i.e(2374),i.e(4833)])}
];
'''


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None, json_error=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _response(self, url):
        response = self.responses.get(url)
        if response is None:
            raise AssertionError(f"测试未配置 URL：{url}")
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, headers=None, timeout=None, **kwargs):
        self.calls.append(("GET", url, headers, None))
        return self._response(url)

    def post(self, url, headers=None, timeout=None, json=None, **kwargs):
        self.calls.append(("POST", url, headers, json))
        return self._response(url)


class VoiceCatalogFetchTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.catalog_path = os.path.join(self.temp_dir.name, "voices.json")
        self.env_patch = patch.dict(
            os.environ,
            {"TTS_VOICE_CATALOG_PATH": self.catalog_path},
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_parse_mimo_document_filters_english_and_skips_cluster_default(self):
        result = fetcher.parse_mimo_voice_document(MIMO_VOICE_TABLE)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            {(entry.voice_id, entry.gender) for entry in result.entries},
            {("Mia", "female"), ("Chloe", "female"), ("Milo", "male"), ("Dean", "male")},
        )
        self.assertNotIn("mimo_default", {entry.voice_id for entry in result.entries})
        self.assertTrue(any("mimo_default" in warning for warning in result.warnings))

    def test_parse_mimo_document_handles_js_escaped_voice_table(self):
        escaped_chunk = json.dumps(MIMO_VOICE_TABLE, ensure_ascii=False)

        result = fetcher.parse_mimo_voice_document(escaped_chunk)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            {entry.voice_id for entry in result.entries},
            {"Mia", "Chloe", "Milo", "Dean"},
        )

    def test_parse_mimo_document_reports_missing_voice_table(self):
        result = fetcher.parse_mimo_voice_document("<html><body>没有音色表</body></html>")

        self.assertFalse(result.ok)
        self.assertTrue(any("音色表" in error for error in result.errors))

    def test_discover_mimo_document_chunk_prefers_english_route(self):
        main_url = "https://mimo.mi.com/static/main.22222222.chunk.js"
        session = FakeSession({main_url: FakeResponse(text=MIMO_MAIN_JS)})

        chunk_url = fetcher.discover_mimo_document_chunk_url(
            session,
            shell_html=MIMO_SHELL,
        )

        self.assertEqual(
            chunk_url,
            "https://mimo.mi.com/static/4833.e7428a0684ae3437.chunk.js",
        )
        self.assertEqual(session.calls[0][1], main_url)

    def test_fetch_mimo_parses_direct_official_table_page(self):
        source_url = "https://mimo.mi.com/docs/models/mimo-v2-5-tts"
        session = FakeSession({source_url: FakeResponse(text=MIMO_VOICE_TABLE)})

        result = fetcher.fetch_mimo_english_voices(session, source_url=source_url)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.source_url, source_url)
        self.assertEqual(len(result.entries), 4)

    def test_fetch_mimo_returns_http_error_without_raising(self):
        source_url = "https://mimo.mi.com/docs/models/mimo-v2-5-tts"
        session = FakeSession({source_url: FakeResponse(status_code=404, text="missing")})

        result = fetcher.fetch_mimo_english_voices(session, source_url=source_url)

        self.assertFalse(result.ok)
        self.assertTrue(any("HTTP 404" in error for error in result.errors))

    def test_parse_minimax_keeps_only_confirmed_english_voices(self):
        payload = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "voice_list": [
                {
                    "voice_id": "English_Trustworthy_Man",
                    "voice_name": "Trustworthy Man",
                    "description": "可靠的英文男声",
                },
                {
                    "voice_id": "custom_english",
                    "voice_name": "Custom English",
                    "language": "English",
                },
                {
                    "voice_id": "Chinese_male",
                    "voice_name": "中文男声",
                    "language": "中文",
                },
            ],
        }

        result = fetcher.parse_minimax_voice_payload(payload)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            {entry.voice_id for entry in result.entries},
            {"English_Trustworthy_Man", "custom_english"},
        )
        self.assertTrue(any("跳过 1 个" in warning for warning in result.warnings))

    def test_parse_minimax_reports_api_error(self):
        result = fetcher.parse_minimax_voice_payload(
            {"base_resp": {"status_code": 1004, "status_msg": "login fail"}}
        )

        self.assertFalse(result.ok)
        self.assertTrue(any("1004" in error for error in result.errors))

    def test_minimax_fetch_uses_bearer_and_does_not_leak_secret(self):
        api_url = "https://api.minimaxi.com/v1/get_voice"
        payload = {
            "base_resp": {"status_code": 0},
            "voice_list": [
                {
                    "voice_id": "English_Trustworthy_Man",
                    "voice_name": "Trustworthy Man",
                    "language": "English",
                }
            ],
        }
        session = FakeSession({api_url: FakeResponse(payload=payload)})

        with patch.object(fetcher, "get_minimax_credentials", return_value="secret-value"):
            result = fetcher.fetch_minimax_english_voices(session, api_url=api_url)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(session.calls[0][2]["Authorization"], "Bearer secret-value")
        self.assertNotIn("secret-value", json.dumps(result.to_dict(), ensure_ascii=False))

    def test_minimax_fetch_reports_missing_credentials(self):
        session = FakeSession({})

        with patch.object(
            fetcher,
            "get_minimax_credentials",
            side_effect=RuntimeError("未配置凭证"),
        ):
            result = fetcher.fetch_minimax_english_voices(session)

        self.assertFalse(result.ok)
        self.assertTrue(any("未找到 MiniMax 凭证" in error for error in result.errors))
        self.assertEqual(session.calls, [])

    def test_empty_result_never_overwrites_existing_catalog(self):
        existing = voice_catalog.VoiceCatalogEntry(
            provider="openai",
            voice_id="Existing",
            display_name="Existing",
            language="en",
            gender="female",
        )
        voice_catalog.save_user_voice_entries((existing,))

        count = fetcher.save_fetched_entries(
            (
                fetcher.ProviderFetchResult(
                    provider="openai",
                    source_url="https://example.invalid",
                    errors=("下载失败",),
                ),
            ),
            replace_existing=True,
        )

        self.assertEqual(count, 0)
        self.assertEqual(
            {entry.voice_id for entry in voice_catalog.load_voice_catalog(include_builtin=False)},
            {"Existing"},
        )

    def test_replace_only_successful_provider_english_entries(self):
        voice_catalog.save_user_voice_entries(
            (
                voice_catalog.VoiceCatalogEntry("openai", "Mia", "Mia", "en", "female"),
                voice_catalog.VoiceCatalogEntry(
                    "minimax", "OldEnglish", "Old English", "en", "male"
                ),
                voice_catalog.VoiceCatalogEntry(
                    "minimax", "ChineseVoice", "中文音色", "zh", "female"
                ),
            )
        )
        new_entry = voice_catalog.VoiceCatalogEntry(
            "minimax", "NewEnglish", "New English", "en", "male"
        )

        count = fetcher.save_fetched_entries(
            (
                fetcher.ProviderFetchResult(
                    provider="minimax",
                    source_url="https://api.minimaxi.com/v1/get_voice",
                    entries=(new_entry,),
                ),
            ),
            replace_existing=True,
        )

        self.assertEqual(count, 1)
        saved = {
            (entry.provider, entry.voice_id)
            for entry in voice_catalog.load_voice_catalog(include_builtin=False)
        }
        self.assertEqual(
            saved,
            {("openai", "Mia"), ("minimax", "ChineseVoice"), ("minimax", "NewEnglish")},
        )

    def test_dry_run_does_not_create_catalog(self):
        result = fetcher.ProviderFetchResult(
            provider="openai",
            source_url="https://example.invalid",
            entries=(
                voice_catalog.VoiceCatalogEntry("openai", "Mia", "Mia", "en", "female"),
            ),
        )
        output = io.StringIO()

        with patch.object(fetcher, "fetch_english_voices", return_value=(result,)):
            with redirect_stdout(output):
                exit_code = fetcher.main(["--provider", "mimo", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(os.path.exists(self.catalog_path))
        self.assertIn("未写入用户音色目录", output.getvalue())

    def test_request_exception_becomes_readable_error(self):
        source_url = "https://mimo.mi.com/docs/models/mimo-v2-5-tts"
        session = FakeSession({source_url: requests.ConnectionError("proxy unavailable")})

        result = fetcher.fetch_mimo_english_voices(session, source_url=source_url)

        self.assertFalse(result.ok)
        self.assertTrue(any("请求 mimo.mi.com 失败" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
