"""构造探针和替代声纹编码器，不产生真实声音库或人工核验结论。"""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.__main__ import main


class VoiceBankMetadataTest(unittest.TestCase):
    def prepare(self, root):
        records = []
        for voice in ('冰糖', '茉莉'):
            for i, text in enumerate(('第一条共同文本。', '第二条共同文本。'), 1):
                path = root / f'{voice}_{i}.wav'
                sf.write(path, .1 * np.sin(np.arange(64000) * .1), 16000, subtype='PCM_16')
                records.append({'voice': voice, 'prompt_id': str(i), 'text': text,
                                'path': str(path), 'verified': True})
        manifest = root / 'fixture_probes.json'
        manifest.write_text(json.dumps({'provider': 'openai', 'model': 'constructed_fixture_only', 'probes': records}))
        return manifest

    def command(self, root):
        return ['build-bank', '--manifest', str(root / 'fixture_probes.json'), '--speaker-model', 'fixture_model',
                '--output', str(root / 'bank.json')]

    def test_bank_retains_audio_hash_signal_rate_and_model_provenance(self):
        class Encoder:
            def cache_identity(self):
                return {'kind': 'fixture', 'fingerprint': 'fixed-fixture-model'}

            def __call__(self, path):
                return np.array([1., 0.]) if '冰糖' in path else np.array([0., 1.])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.prepare(root)
            with patch('audiobook_generator.audio_core.backends.SpeakerEncoder', lambda _: Encoder()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(self.command(root)), 0)
            bank = json.loads((root / 'bank.json').read_text())
            self.assertEqual(bank['speaker_model_identity']['fingerprint'], 'fixed-fixture-model')
            self.assertEqual(bank['probe_manifest_sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
            for voice in bank['voices'].values():
                for record in voice['probes'].values():
                    self.assertEqual(record['audio_sha256'], hashlib.sha256(Path(record['path']).read_bytes()).hexdigest())
                    self.assertEqual(record['metrics']['duration_seconds'], 4)
                    self.assertIn('median_hz', record['metrics']['pitch'])
                    self.assertIn('rms_dbfs', record['metrics'])
                    self.assertGreater(record['metrics']['overall_rate'], 0)
                    self.assertGreater(record['metrics']['articulation_rate'], 0)
                    self.assertEqual(record['reading_unit_kind'], 'normalized_han_characters')
            self.assertEqual(bank['verification_origin'], 'caller_supplied_manifest')

    def test_bank_rejects_mixed_model_revisions_before_writing_output(self):
        class Encoder:
            def __init__(self):
                self.identities = 0

            def cache_identity(self):
                self.identities += 1
                return {'fingerprint': str(self.identities)}

            def __call__(self, path):
                return np.array([1., 0.])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            with patch('audiobook_generator.audio_core.backends.SpeakerEncoder', lambda _: Encoder()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(self.command(root)), 2)
            self.assertIn('建库期间声纹模型版本变化', stderr.getvalue())
            self.assertFalse((root / 'bank.json').exists())

    def test_bank_rejects_audio_changed_during_feature_extraction(self):
        class Encoder:
            def cache_identity(self):
                return {'fingerprint': 'fixed-fixture-model'}

            def __call__(self, path):
                samples, rate = sf.read(path, dtype='int16')
                samples[0] = 12345
                sf.write(path, samples, rate, subtype='PCM_16')
                return np.array([1., 0.])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            with patch('audiobook_generator.audio_core.backends.SpeakerEncoder', lambda _: Encoder()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(self.command(root)), 2)
            self.assertIn('建库期间探针音频发生变化', stderr.getvalue())
            self.assertFalse((root / 'bank.json').exists())
