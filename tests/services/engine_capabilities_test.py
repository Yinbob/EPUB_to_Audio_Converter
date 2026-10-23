"""迁移后的引擎目录与真实请求边界；不加载模型或调用网络。"""
import io
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from audiobook_generator.services.capabilities import capabilities
from audiobook_generator.services.common import ServiceError
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.models import Generation, VoxCPM


class EngineCapabilitiesTest(unittest.TestCase):
    def test_voice_labels_preserve_callable_ids(self):
        providers = {item['id']: item for item in capabilities()}
        for provider in providers.values():
            for choice in provider['voices']:
                self.assertIsInstance(choice['value'], str)
                self.assertIsInstance(choice['label'], str)
            default = provider['defaults'].get('voice_name') or provider['defaults'].get('voice')
            if default:
                self.assertIn(default, [choice['value'] for choice in provider['voices']])
        minimax = providers['minimax']['voices']
        self.assertIn({'value': 'male-qn-qingse', 'label': '青涩青年音色'}, minimax)
        self.assertIn('chatterbox-v0.5', providers['chatterbox']['models'])
        self.assertTrue(any(choice['value'] == 'saved_bryce_young_en'
                            for choice in providers['openai']['role_voices']))

    def test_preserved_defaults_and_advanced_inputs(self):
        providers = {item['id']: item for item in capabilities()}
        self.assertFalse(providers['openai']['defaults']['stream'])
        self.assertEqual(providers['edge']['defaults']['break_duration'], 1250)
        self.assertTrue(providers['voxcpm']['defaults']['denoise'])
        self.assertFalse(providers['voxcpm']['defaults']['auto_transcribe'])
        engine = VoxCPM(provider='voxcpm', device='cuda:12', model_name='/models/custom',
                        voice='file:我的声音.wav')
        self.assertEqual(engine.device, 'cuda:12')
        with self.assertRaises(ValidationError):
            VoxCPM(provider='voxcpm', device='cuda:other')
        self.assertEqual(Generation(log_level='CRITICAL').log_level, 'CRITICAL')
        self.assertEqual(Generation().file_ids, [])
        self.assertIn('voice_name', providers['minimax']['custom_fields'])
        self.assertIn('model_name', providers['voxcpm']['custom_fields'])

    def test_catalog_documents_and_aac_reference_can_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            files = FileStore(Path(directory))
            for suffix in ('.json', '.txt', '.csv', '.tsv', '.md', '.html', '.htm', '.docx', '.pdf', '.aac'):
                file = files.upload('音色说明' + suffix, io.BytesIO(b'fixture'))
                self.assertEqual(files.resolve(file['id']).suffix, suffix)
            with self.assertRaises(ServiceError):
                # 可执行文件仍不能作为说明文档上传。
                files.upload('音色.py', io.BytesIO(b'fixture'))


if __name__ == '__main__':
    unittest.main()
