"""验证统一增益不改变条件差异、样本位置或来源，不模拟听感通过。"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.experiment_loudness import prepare_casting_gain
from audiobook_generator.audio_core.repair_review import _read_report, _sha
from tests.audiobook_generator.audio_core import loudness_preview_test as fixture


class ExperimentLoudnessTest(unittest.TestCase):
    def sources(self, root):
        conditions = []
        for ci in range(2):
            paths = []
            for si in range(2):
                folder = root/f'c{ci}s{si}'
                folder.mkdir()
                path, report = fixture.LoudnessPreviewTest().source(folder)
                report['chapter_index'] = ci*2+si+1
                report['quality_status'] = 'incomplete'
                report['boundaries'] = []
                for i, item in enumerate(report['chunks']):
                    chunk = item['chunk']
                    chunk.update(unit_id=str(i), source_text=f'scene{si} part{i}',
                        source_start=0, source_end=10, profile={'voice': ['Mia','Chloe'][(i+ci)%2]})
                    item['report'] = {'metrics': {}}
                path.write_text(json.dumps(report))
                paths.append(str(path))
            conditions.append({'condition': str(ci), 'report_paths': paths})
        return conditions

    def test_common_protocol_exact_waveforms_timing_and_draft_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); conditions = self.sources(root)
            before = {p: Path(p).read_bytes() for c in conditions for p in c['report_paths']}
            cp = root/'conditions.json'; cp.write_text(json.dumps(conditions))
            gp = root/'gains.json'; gp.write_text(json.dumps({'Mia':0, 'Chloe':-5}))
            with patch('openai.OpenAI') as remote, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['prepare-casting-gain','--conditions',str(cp),'--gains',str(gp),
                                       '--output',str(root/'pack')]),0)
                remote.assert_not_called()
            manifest = json.loads((root/'pack/manifest.json').read_text())
            self.assertFalse(manifest['human_verified']); self.assertFalse(manifest['ready_for_listeners'])
            self.assertEqual(manifest['requests_sent'],0)
            for f in manifest['files']:
                self.assertEqual(_sha(root/'pack'/f['path']),f['sha256'])
            for row in manifest['sources']:
                old=json.loads(Path(row['source_report']).read_text())
                new=json.loads(Path(row['descriptor']).read_text())
                self.assertEqual(new['assembly']['boundaries'],old['assembly']['boundaries'])
                original,rate=sf.read(old['output_file'],dtype='int16',always_2d=True)
                expected=original.copy()
                for olditem,newitem,span in zip(old['chunks'],new['chunks'],old['assembly']['spans']):
                    self.assertEqual(olditem['chunk'],newitem['chunk'])
                    gain=1 if olditem['chunk']['profile']['voice']=='Mia' else 10**(-5/20)
                    a,b=span['start_sample'],span['end_sample']
                    expected[a:b]=np.rint(original[a:b].astype(float)*gain).astype(np.int16)
                    actual,_=sf.read(newitem['rendered_path'],dtype='int16',always_2d=True)
                    np.testing.assert_array_equal(expected[a:b],actual)
                actual,newrate=sf.read(new['output_file'],dtype='int16',always_2d=True)
                self.assertEqual(rate,newrate); np.testing.assert_array_equal(expected,actual)
                with self.assertRaisesRegex(ValueError,'离线复评'):
                    _read_report(row['descriptor'])
            for p,value in before.items(): self.assertEqual(Path(p).read_bytes(),value)
            with self.assertRaisesRegex(ValueError,'已存在'):
                prepare_casting_gain(conditions,{'Mia':0,'Chloe':-5},root/'pack')

    def test_no_implicit_voice_gain_or_invalid_or_confounded_conditions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); conditions=self.sources(root)
            for gains in ({'Mia':0}, {'Mia':0,'Chloe':-5,'other':0}, {'Mia':True,'Chloe':-5},
                          {'Mia':0,'Chloe':-13}, {'Mia':0,'Chloe':float('nan')}, {'Mia':0,'Chloe':1}):
                with self.subTest(gains=gains),self.assertRaises(ValueError):
                    prepare_casting_gain(conditions,gains,root/'bad')
                self.assertFalse((root/'bad').exists())
            for mutation in ('order','duplicate','role_voice','composition','reviewed'):
                changed=copy.deepcopy(conditions)
                if mutation=='order': changed[1]['report_paths'].reverse()
                elif mutation=='duplicate': changed[1]['report_paths']=changed[0]['report_paths']
                else:
                    p=Path(changed[1]['report_paths'][1]); saved=p.read_text(); d=json.loads(saved)
                    if mutation=='role_voice':d['chunks'][0]['chunk']['profile']['voice']='Mia'
                    elif mutation=='composition':d['chunks'][0]['composition']={'not_supported':True}
                    else:d['human_adjudication']={'not_transferable':True}
                    p.write_text(json.dumps(d))
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                    prepare_casting_gain(changed,{'Mia':0,'Chloe':-5},root/'bad')
                self.assertFalse((root/'bad').exists())
                if mutation not in ('order','duplicate'): p.write_text(saved)

    def test_mid_export_source_change_aborts_without_partial_pack(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); conditions=self.sources(root)
            source_path=Path(conditions[0]['report_paths'][0])
            original_write=sf.write
            def changed(*args,**kwargs):
                result=original_write(*args,**kwargs)
                source_path.write_text(source_path.read_text()+' ')
                return result
            with patch('audiobook_generator.audio_core.experiment_loudness.sf.write',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'来源变化'):
                    prepare_casting_gain(conditions,{'Mia':0,'Chloe':-5},root/'bad')
            self.assertFalse((root/'bad').exists())

    def test_reevaluation_updates_stage_without_fabricating_content_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); conditions=self.sources(root)
            prepare_casting_gain(conditions,{'Mia':0,'Chloe':-5},root/'pack')
            descriptor=root/'pack/condition_01/scene_01/descriptor.json'
            target=descriptor.with_name('quality.json')
            with patch('openai.OpenAI') as remote,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['evaluate','--manifest',str(descriptor),'--output',str(target),
                                       '--no-asr','--no-speaker']),0)
                remote.assert_not_called()
            report=json.loads(target.read_text())
            self.assertFalse(report['experiment_conditioning']['quality_pending_reevaluation'])
            self.assertEqual(report['final_verification']['dimensions']['encoding'],'passed')
            self.assertNotEqual(report['chunks'][0]['report']['dimensions']['content'],'passed')
            self.assertFalse(report['experiment_conditioning']['human_verified'])


if __name__=='__main__':
    unittest.main()
