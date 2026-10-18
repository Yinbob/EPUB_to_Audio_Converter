"""构造控制只检验局部增益、来源和失败门禁，不是实际听感结论。"""
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
from audiobook_generator.audio_core.loudness_preview import prepare_loudness_preview


class LoudnessPreviewTest(unittest.TestCase):
    def source(self, root):
        paths, spans, chunks, pieces = [], [], [], []
        cursor = 0
        # 不同波形、非零上下文和补充静音用于检测错误的处理范围。
        for i in range(3):
            pcm = np.rint(7000*np.sin(np.arange(40000)*(.04+i*.01))).astype(np.int16)
            path = root/f'chunk{i}.wav'
            sf.write(path, pcm, 16000, subtype='PCM_16')
            paths.append(path)
            spans.append({'chunk_id':str(i),'start_sample':cursor,'end_sample':cursor+len(pcm),
                          'render_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            chunks.append({'chunk':{'chunk_id':str(i),'role_id':str(i),'tts_text':['甲','乙','丙'][i]},
                           'rendered_path':str(path)})
            pieces.extend([pcm, np.zeros(1600,dtype=np.int16)] if i<2 else [pcm])
            cursor += len(pcm)+(1600 if i<2 else 0)
        output=root/'full.wav'
        sf.write(output,np.concatenate(pieces),16000,subtype='PCM_16')
        joins=[{'boundary_id':f'{i}|{i+1}','left_chunk_id':str(i),'right_chunk_id':str(i+1),
                'start_sample':spans[i]['end_sample'],'end_sample':spans[i+1]['start_sample']}
               for i in range(2)]
        report={'schema_version':'audio-core-v1','provider':'openai','generation_status':'generated',
                'source_group_id':'constructed','output_file':str(output),'chunks':chunks,
                'assembly':{'sample_rate':16000,'channels':1,'total_samples':cursor,'spans':spans,'boundaries':joins},
                'final_verification':{'dimensions':{'encoding':'passed'},
                   'metrics':{'encoded_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}}}
        path=root/'quality.json';path.write_text(json.dumps(report))
        return path,report

    def measurements(self):
        return [{'integrated_lufs':-23.}, {'integrated_lufs':-18.}, {'integrated_lufs':-23.}]

    def test_attenuation_preserves_positions_context_and_sources_and_cli_is_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,report=self.source(root);before=path.read_bytes()
            stdout=io.StringIO()
            with patch('audiobook_generator.audio_core.loudness_preview.measure_loudness',side_effect=self.measurements()), \
                    patch('openai.OpenAI') as remote,contextlib.redirect_stdout(stdout):
                self.assertEqual(main(['preview-loudness','--report',str(path),'--boundary','0|1',
                                       '--output',str(root/'preview')]),0)
                remote.assert_not_called()
            result=json.loads(stdout.getvalue());self.assertEqual(result['requests_sent'],0)
            original,_=sf.read(root/'preview/audio/original_full.wav',dtype='int16')
            candidate,_=sf.read(root/'preview/audio/matched_full.wav',dtype='int16')
            source,_=sf.read(report['output_file'],dtype='int16')
            start,end=report['assembly']['spans'][1]['start_sample'],report['assembly']['spans'][1]['end_sample']
            expected=source.copy();expected[start:end]=np.rint(expected[start:end]*10**(-5/20)).astype(np.int16)
            np.testing.assert_array_equal(source,original)
            np.testing.assert_array_equal(expected,candidate)
            self.assertEqual(len(candidate),len(source))
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(result['automatically_applied'])
            self.assertEqual(result['content_checks'],{'original_pair':'not_evaluated','matched_pair':'not_evaluated'})
            with self.assertRaisesRegex(ValueError,'已存在'):
                prepare_loudness_preview(path,'0|1',root/'preview')

    def test_gain_is_bounded_and_failed_measurement_does_not_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,_=self.source(root)
            with patch('audiobook_generator.audio_core.loudness_preview.measure_loudness',side_effect=self.measurements()):
                r=prepare_loudness_preview(path,'0|1',root/'limited',max_attenuation_db=2)
            self.assertEqual(r['attenuation_db'],2)
            with patch('audiobook_generator.audio_core.loudness_preview.measure_loudness',side_effect=ValueError('silent')):
                with self.assertRaisesRegex(ValueError,'silent'):
                    prepare_loudness_preview(path,'0|1',root/'failed')
            self.assertFalse((root/'failed').exists())
            with patch('audiobook_generator.audio_core.loudness_preview.measure_loudness',return_value={'integrated_lufs':-23.}):
                with self.assertRaisesRegex(ValueError,'并未测得更响'):
                    prepare_loudness_preview(path,'0|1',root/'equal')
            for value in (True,0,-1,13,float('nan')):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    prepare_loudness_preview(path,'0|1',root/'bad',max_attenuation_db=value)

    def test_tampered_source_and_rendered_chunk_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,report=self.source(root)
            rendered=Path(report['chunks'][1]['rendered_path'])
            rendered.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'校验值不一致'):
                prepare_loudness_preview(path,'0|1',root/'bad')
            self.assertFalse((root/'bad').exists())

    def test_content_disagreement_and_model_change_remain_visible(self):
        class Evaluator:
            def __init__(self): self.identity='fixture'
            def backend_identity(self,kind): return {'fingerprint':self.identity}
            def transcript(self,path): return '甲乙' if 'original' in str(path) else '甲'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,_=self.source(root)
            with patch('audiobook_generator.audio_core.loudness_preview.measure_loudness',side_effect=self.measurements()):
                r=prepare_loudness_preview(path,'0|1',root/'pack',evaluator=Evaluator())
            self.assertEqual(r['content_checks'],{'original_pair':'no_asr_difference','matched_pair':'asr_difference'})
            evaluator=Evaluator()
            def changed(path):
                evaluator.identity='changed'
                return '甲乙'
            evaluator.transcript=changed
            with patch('audiobook_generator.audio_core.loudness_preview.measure_loudness',side_effect=self.measurements()):
                with self.assertRaisesRegex(ValueError,'模型变化'):
                    prepare_loudness_preview(path,'0|1',root/'bad',evaluator=evaluator)
            self.assertFalse((root/'bad').exists())


if __name__=='__main__':
    unittest.main()
