import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.backends import SenseVoiceBackend, SpeakerEncoder
from audiobook_generator.audio_core.model_identity import local_model_identity
from audiobook_generator.audio_core.models import CoreOptions
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class FileBackend:
    def __init__(self, root, kind='asr', mutate=False):
        self.root, self.kind, self.calls, self.mutate = root, kind, 0, mutate

    def cache_identity(self):
        return local_model_identity(self.kind, self.root)

    def __call__(self, path):
        self.calls += 1
        text = (self.root / 'model.pt').read_text()
        if self.mutate:
            (self.root / 'model.pt').write_text(text + '变更')
        return text if self.kind == 'asr' else np.array([1., 0.]) if text == '你好' else np.array([0., 1.])


class ModelIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'model'
        self.model.mkdir()
        (self.model / 'model.pt').write_text('你好')
        self.audio = self.root / 'sound.wav'
        sf.write(self.audio, .1 * np.sin(np.arange(64000) * .1), 16000, subtype='PCM_16')
        self.store = ArtifactStore(self.root / 'project')

    def test_hash_tracks_same_size_replacements_and_configuration_but_ignores_readme(self):
        first = local_model_identity('asr', self.model)
        (self.model / 'README.md').write_text('documentation only')
        self.assertEqual(first, local_model_identity('asr', self.model))
        weight = self.model / 'model.pt'
        original = weight.stat()
        weight.write_text('再见')
        os.utime(weight, ns=(original.st_atime_ns, original.st_mtime_ns))
        second = local_model_identity('asr', self.model)
        self.assertNotEqual(first['fingerprint'], second['fingerprint'])
        (self.model / 'config.yaml').write_text('normalization: changed')
        self.assertNotEqual(second['fingerprint'], local_model_identity('asr', self.model)['fingerprint'])

    def test_disk_and_memory_transcripts_invalidate_when_weights_change_at_same_path(self):
        first = FileBackend(self.model)
        evaluator = QualityEvaluator(transcribe=first, store=self.store)
        self.assertEqual(evaluator.transcript(self.audio), '你好')
        second = FileBackend(self.model)
        self.assertEqual(QualityEvaluator(transcribe=second, store=self.store).transcript(self.audio), '你好')
        self.assertEqual(second.calls, 0)
        (self.model / 'model.pt').write_text('再见')
        self.assertEqual(evaluator.transcript(self.audio), '再见')
        self.assertEqual(first.calls, 2)
        self.assertEqual(len(list((self.store.root / 'asr').glob('*.json'))), 2)

    def test_corrupt_or_empty_transcript_cache_is_recomputed(self):
        backend = FileBackend(self.model)
        self.assertEqual(QualityEvaluator(transcribe=backend, store=self.store).transcript(self.audio), '你好')
        cache = next((self.store.root / 'asr').glob('*.json'))
        value = json.loads(cache.read_text())
        for content in ('{broken', json.dumps({**value, 'text': ''})):
            cache.write_text(content)
            self.assertEqual(QualityEvaluator(transcribe=backend, store=self.store).transcript(self.audio), '你好')
        self.assertEqual(backend.calls, 3)

    def test_unversioned_custom_callables_do_not_share_disk_cache(self):
        a = QualityEvaluator(transcribe=lambda _: '你好', store=self.store)
        b = QualityEvaluator(transcribe=lambda _: '不同转写器', store=self.store)
        self.assertEqual(a.transcript(self.audio), '你好')
        self.assertEqual(b.transcript(self.audio), '不同转写器')

    def test_embedding_invalidates_and_mid_inference_model_change_is_rejected(self):
        backend = FileBackend(self.model, kind='speaker')
        evaluator = QualityEvaluator(speaker=backend)
        np.testing.assert_array_equal(evaluator.embedding(self.audio), [1., 0.])
        (self.model / 'model.pt').write_text('再见')
        np.testing.assert_array_equal(evaluator.embedding(self.audio), [0., 1.])
        self.assertEqual(backend.calls, 2)
        for kind in ('asr', 'speaker'):
            mutating = FileBackend(self.model, kind=kind, mutate=True)
            evaluator = QualityEvaluator(**{'transcribe' if kind == 'asr' else 'speaker': mutating})
            with self.assertRaisesRegex(RuntimeError, '模型版本变化'):
                (evaluator.transcript if kind == 'asr' else evaluator.embedding)(self.audio)

    def test_sensevoice_loader_reloads_same_directory_for_new_content_revision(self):
        from audiobook_generator.utils import voxcpm_asr
        fake = MagicMock()
        fake.AutoModel.return_value.generate.return_value = [{'text': '你好'}]
        with patch.dict('sys.modules', {'funasr': fake}), patch.object(voxcpm_asr, '_asr_model', None), \
                patch.object(voxcpm_asr, '_asr_device', None), patch.object(voxcpm_asr, '_asr_model_id', None), \
                patch.object(voxcpm_asr, '_asr_model_revision', None):
            backend = SenseVoiceBackend(str(self.model))
            backend(self.audio)
            backend(self.audio)
            self.assertEqual(fake.AutoModel.call_count, 1)
            (self.model / 'model.pt').write_text('新权重')
            backend(self.audio)
            self.assertEqual(fake.AutoModel.call_count, 2)

    def test_speaker_loader_reloads_same_directory_for_new_weights(self):
        for name in ('hyperparams.yaml', 'embedding_model.ckpt', 'mean_var_norm_emb.ckpt', 'classifier.ckpt', 'label_encoder.txt'):
            (self.model / name).write_text('constructed fixture')
        classifier = MagicMock()
        classifier.from_hparams.return_value.encode_batch.return_value.cpu.return_value.numpy.return_value = np.array([1., 0.])
        tensor = MagicMock()
        torch = SimpleNamespace(inference_mode=contextlib.nullcontext, from_numpy=lambda _: tensor)
        with patch.dict('sys.modules', {'speechbrain.inference.speaker': SimpleNamespace(EncoderClassifier=classifier), 'torch': torch}):
            backend = SpeakerEncoder(str(self.model))
            backend(self.audio)
            backend(self.audio)
            self.assertEqual(classifier.from_hparams.call_count, 1)
            (self.model / 'embedding_model.ckpt').write_text('updated fixture')
            backend(self.audio)
            self.assertEqual(classifier.from_hparams.call_count, 2)

    def test_role_anchor_identity_changes_with_same_path_model_replacement(self):
        options = CoreOptions(asr_model_dir=str(self.model), enable_speaker=False)
        provider = ObservedFake()
        for text in ('version_a', 'version_b'):
            (self.model / 'model.pt').write_text(text)
            result = run_chapter(plan_for(('开场。',)), provider, self.root / 'out.wav', AudioTags('章', '作者', '书', 1),
                self.store.root, options=options, evaluator=QualityEvaluator(options, transcribe=lambda _: '开场。'))
            self.assertEqual(result['chunks'][0]['report']['metrics']['consistency_reference'], 'not_available')
        self.assertEqual(len(provider.calls), 1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM role_anchors').fetchone()[0], 2)
