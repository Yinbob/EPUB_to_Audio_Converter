"""返工以实际合成内容为边界，审阅解释和本机路径不进入音频身份。"""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from audiobook_generator.services.models import Generation
from audiobook_generator.services.research_render import render_snapshot, changed_chapters, prepare_regeneration, clean_params
from tests.audiobook_generator.role_script.research_test import state


class ResearchRenderTest(unittest.TestCase):
    def test_explanations_do_not_change_audio_but_voice_pause_and_endpoint_do(self):
        s = state()
        unit = SimpleNamespace(text='你好', profile=SimpleNamespace(provider_params={'voice': '茉莉', 'speed': 1}),
            tone=None, pause_after_ms=250)
        plan = SimpleNamespace(chapter_index=1, provider='openai', output_format='mp3', units=[unit])
        g = Generation()
        with patch('audiobook_generator.services.portable_voices.endpoint_for', return_value='https://host:443/v1'):
            before = render_snapshot([plan], g, s)
            changed = copy.deepcopy(s)
            changed['decisions']['ch1_s2']['against'] = []
            changed['decisions']['ch1_s2']['analyzer_version'] = 'new explanation'
            after = render_snapshot([plan], g, changed)
            baseline = {'id': 'old', 'revision': 1, 'status': 'succeeded', 'render_snapshot': before}
            self.assertEqual(changed_chapters(after, baseline), [])
            unit.pause_after_ms = 500
            self.assertEqual(changed_chapters(render_snapshot([plan], g, changed), baseline), [1])
            unit.pause_after_ms = 250
        with patch('audiobook_generator.services.portable_voices.endpoint_for', return_value='https://host:8443/v1'):
            self.assertEqual(changed_chapters(render_snapshot([plan], g, s), baseline), [1])

    def test_reference_content_hash_and_unique_repair_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory, 'reference.wav')
            reference.write_bytes(b'first')
            before = clean_params({'reference_audio_path': str(reference), 'api_key': 'secret'})
            reference.write_bytes(b'second')
            after = clean_params({'reference_audio_path': str(reference)})
            self.assertNotEqual(before, after)
            self.assertNotIn(directory, str(after))
            self.assertNotIn('secret', str(before))
            snapshot = {'book_sha256': 'book', 'revision': 2, 'chapters': {'1': {'digest': 'new'}}}
            baseline = {'id': 'old', 'status': 'succeeded', 'render_snapshot': {'book_sha256': 'book', 'chapters': {}}}
            config = SimpleNamespace(output_folder=directory)
            a = prepare_regeneration(config, snapshot, baseline)[0]
            b = prepare_regeneration(config, snapshot, baseline)[0]
            self.assertNotEqual(a.output_folder, b.output_folder)

    def test_failed_baseline_retries_only_incomplete_or_changed_chapters(self):
        from audiobook_generator.services.common import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            atomic_json(Path(directory, 'manifest.json'), {'completed_chapters': [1]})
            snapshot = {'book_sha256': 'book', 'revision': 2, 'chapters': {str(i): {'digest': 'same'} for i in (1, 2)}}
            baseline = {'id': 'old', 'status': 'failed', 'output_dirs': [directory], 'render_snapshot': snapshot}
            self.assertEqual(changed_chapters(snapshot, baseline), [2])
