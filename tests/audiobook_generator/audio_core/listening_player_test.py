"""纯脚本事件与CSV互操作检验，不启动浏览器，不写真实参与者结果。"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from audiobook_generator.audio_core.listening import prepare_listening, score_listening
from tests.audiobook_generator.audio_core import listening_test as fixtures


class ListeningPlayerLogicTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), '未安装Node，跳过纯脚本检验')
    def test_offline_event_logic_exports_partial_csv_accepted_by_scorer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepare_listening(fixtures.ListeningTest().conditions(root),root/'pack')
            result = subprocess.run([shutil.which('node'),str(Path(__file__).with_suffix('.js')),
                str(root/'pack/public/index.html')],capture_output=True,text=True,check=True,timeout=10)
            data = json.loads(result.stdout)
            self.assertTrue(data['synthetic_only'])
            response_path = root/'synthetic_qa.csv'
            response_path.write_text(data['csv'],encoding='utf-8')
            score = score_listening(root/'pack/private_answer_key.json',response_path)
            self.assertEqual(sum(c['total'] for c in score['conditions'].values()),1)
            self.assertEqual(sum(c['participants'] for c in score['conditions'].values()),1)


if __name__ == '__main__':
    unittest.main()
