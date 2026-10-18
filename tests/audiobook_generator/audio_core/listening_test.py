"""辨识材料的质量隔离与来源完整性；构造音频和回答不计入听众实验。"""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.listening import prepare_listening, score_listening


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ListeningTest(unittest.TestCase):
    def conditions(self, root):
        result = []
        for condition in ("interaction", "random"):
            folder = root / condition
            folder.mkdir()
            chunks, spans, samples, boundaries = [], [], [], []
            frames, rate = 51200, 16000
            for i, role in enumerate(("alice", "bob", "alice", "bob")):
                path = folder / f"chunk{i}.wav"
                sf.write(path, .1 * np.sin(np.arange(frames) * (.03 + i * .01)), rate, subtype="PCM_16")
                samples.append(sf.read(path, dtype="int16")[0])
                chunk = {"chunk_id": f"c{i}", "role_id": role, "source_text": f"Sentence {i}.",
                         "tts_text": f"Sentence {i}.", "language": "en"}
                chunks.append({"chunk": chunk, "rendered_path": str(path), "report": {
                    "dimensions": {"signal": "passed", "content": "passed", "consistency": "incomplete"},
                    "issues": []}})
                spans.append({"chunk_id": f"c{i}", "start_sample": i * frames, "end_sample": (i + 1) * frames,
                              "render_sha256": sha(path)})
                if i:
                    boundaries.append({"left_chunk_id": f"c{i-1}", "right_chunk_id": f"c{i}",
                                       "start_sample": i * frames, "end_sample": i * frames})
            pcm = folder / "chapter.wav"
            sf.write(pcm, np.concatenate(samples), rate, subtype="PCM_16")
            final = folder / "final.wav"
            final.write_bytes(pcm.read_bytes())
            report = {"schema_version": "audio-core-v1", "provider": "openai", "generation_status": "generated",
                "quality_status": "incomplete", "source_group_id": "constructed-source", "chunks": chunks,
                "output_file": str(final), "assembly": {"sample_rate": rate, "channels": 1,
                    "total_samples": frames * 4, "spans": spans, "boundaries": boundaries},
                "boundaries": [{"dimensions": {"stitching": "incomplete", "content": "passed"},
                                "issues": []} for _ in boundaries],
                "final_verification": {"dimensions": {"encoding": "passed", "content": "passed"}, "issues": [],
                    "metrics": {"encoded_sha256": sha(final), "reference_pcm_sha256": sha(pcm)}}}
            report_path = folder / "quality.json"
            report_path.write_text(json.dumps(report))
            result.append({"condition": condition, "report_path": str(report_path)})
        return result

    def edit(self, condition, mutate):
        path = Path(condition["report_path"])
        data = json.loads(path.read_text())
        mutate(data)
        path.write_text(json.dumps(data))

    def rows(self, path):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def write_rows(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def multi_scene_conditions(self, root):
        result = [{'condition': c, 'report_paths': []} for c in ('interaction', 'random')]
        for scene_index, role_order in enumerate((('alice', 'bob', 'alice', 'casey'),
                                                  ('bob', 'casey', 'bob', 'alice')), 1):
            scene = root / f'scene{scene_index}'
            scene.mkdir()
            conditions = self.conditions(scene)
            for destination, condition in zip(result, conditions):
                def update(report):
                    report['source_group_id'] = f'constructed-scene-{scene_index}'
                    for index, (item, role) in enumerate(zip(report['chunks'], role_order)):
                        item['chunk'].update(role_id=role, source_text=f'Scene {scene_index} sentence {index}.',
                            tts_text=f'Scene {scene_index} sentence {index}.',
                            profile={'voice': 'Chloe' if role == 'bob' else 'Mia'})
                self.edit(condition, update)
                destination['report_paths'].append(condition['report_path'])
        return result

    def test_cross_scene_pool_covers_rare_role_and_binds_reference_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conditions = self.multi_scene_conditions(root)
            result = prepare_listening(conditions, root / 'pack')
            self.assertEqual(result['trials'], 16)
            key_path = root / 'pack/private_answer_key.json'
            key = json.loads(key_path.read_text())
            self.assertEqual(len(key['sources']), 4)
            for condition in ('interaction', 'random'):
                answers = [a for a in key['answers'].values() if a['condition'] == condition]
                self.assertEqual({a['source_role'] for a in answers}, {'alice', 'bob', 'casey'})
                casey = [a for a in answers if a['source_role'] == 'casey']
                self.assertEqual(len(casey), 2)
                for answer in casey:
                    reference = answer['reference_sources'][answer['correct_role']]
                    self.assertNotEqual(reference['report_path'], answer['target_source']['report_path'])
                    self.assertNotEqual(reference['source_group_id'], answer['source_group_id'])
                    self.assertEqual(reference['report_sha256'], sha(reference['report_path']))
            public = root / 'pack/public'
            payload = json.loads((public / 'trials.json').read_text())
            for trial in payload['trials']:
                self.assertEqual(len(trial['reference_voices']), 3)
                self.assertNotIn(trial['audio'], trial['reference_voices'].values())
            self.assertEqual(score_listening(key_path, public / 'responses.csv')['conditions'], {})
            for name in ('README.md', 'trials.json', 'responses.csv'):
                text = (public / name).read_text()
                for secret in ('interaction', 'random', 'alice', 'bob', 'casey', str(root)):
                    self.assertNotIn(secret, text)

    def test_single_scene_must_not_silently_drop_rare_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            multi = self.multi_scene_conditions(root)
            conditions = [{'condition': c['condition'], 'report_path': c['report_paths'][0]} for c in multi]
            with self.assertRaisesRegex(ValueError, '至少两个不同的三秒片段'):
                prepare_listening(conditions, root / 'pack')
            self.assertFalse((root / 'pack').exists())

    def test_cross_scene_order_voice_and_quality_mismatches_are_rejected(self):
        for change in ('order', 'voice', 'missing_voice', 'quality', 'role'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                conditions = self.multi_scene_conditions(root)
                condition = {'report_path': conditions[1]['report_paths'][1]}
                if change == 'order':
                    conditions[1]['report_paths'].reverse()
                elif change == 'voice':
                    self.edit(condition, lambda r: r['chunks'][1]['chunk']['profile'].update(voice='Milo'))
                elif change == 'missing_voice':
                    self.edit(condition, lambda r: r['chunks'][1]['chunk'].pop('profile'))
                elif change == 'quality':
                    self.edit(condition, lambda r: r['chunks'][1]['report']['dimensions'].update(content='incomplete'))
                else:
                    # 第二场景的角色归属必须与其他条件一致。
                    self.edit(condition, lambda r: r['chunks'][1]['chunk'].update(role_id='alice'))
                with self.assertRaises(ValueError):
                    prepare_listening(conditions, root / 'pack')
                self.assertFalse((root / 'pack').exists())

    def hybrid_conditions(self, root):
        conditions = self.multi_scene_conditions(root)
        first = json.loads(Path(conditions[0]['report_paths'][0]).read_text())
        reference = root/'clone_reference.wav'
        reference.write_bytes(Path(first['chunks'][0]['rendered_path']).read_bytes())
        for condition in conditions:
            for report_path in condition['report_paths']:
                def update(report):
                    for item in report['chunks']:
                        role = item['chunk']['role_id']
                        mode = {'alice':'clone', 'bob':'design', 'casey':'preset'}[role]
                        profile = {'voice_mode':mode, 'voice_profile_id':role,
                                   'voice_version':'v1', 'voice_language':'en',
                                   'instructions':'Stable audiobook voice.'}
                        if mode == 'clone':
                            profile.update(reference_audio_path=str(reference),reference_audio_sha256=sha(reference))
                        elif mode == 'design': profile['voice_description'] = 'Distinctive warm adult voice.'
                        else: profile['voice'] = 'Mia'
                        item['chunk']['profile'] = profile
                        item['voice_reference_request'] = {
                            'mode':mode, 'model':{'preset':'mimo-v2.5-tts','clone':'mimo-v2.5-tts-voiceclone',
                                'design':'mimo-v2.5-tts-voicedesign'}[mode],
                            'voice':profile.get('voice'), 'voice_profile_id':role,
                            'voice_version':'v1','language':'en','instructions':'Stable audiobook voice.',
                            **({k:profile[k] for k in ('reference_audio_path','reference_audio_sha256')}
                               if mode == 'clone' else {})}
                self.edit({'report_path':report_path},update)
        return conditions

    def test_hybrid_cross_scene_reference_pool_and_public_blinding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); conditions = self.hybrid_conditions(root)
            with patch('openai.OpenAI') as remote:
                result = prepare_listening(conditions,root/'pack')
                remote.assert_not_called()
            self.assertEqual(result['trials'],16)
            key = json.loads((root/'pack/private_answer_key.json').read_text())
            self.assertEqual({a['source_role'] for a in key['answers'].values()},{'alice','bob','casey'})
            for name in ('trials.json','README.md','responses.csv'):
                public = (root/'pack/public'/name).read_text()
                for private in ('Distinctive warm adult','mimo-v2.5','clone_reference','voice_version'):
                    self.assertNotIn(private,public)

    def test_same_preset_name_cannot_hide_changed_version_or_request(self):
        for field in ('voice_version','voice_profile_id','instructions'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); conditions = self.multi_scene_conditions(root)
                condition = {'report_path':conditions[0]['report_paths'][1]}
                self.edit(condition, lambda report: report['chunks'][1]['chunk']['profile'].update({field:'changed'}))
                with self.assertRaisesRegex(ValueError,'声音档案版本'):
                    prepare_listening(conditions,root/'pack')
                self.assertFalse((root/'pack').exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); conditions = self.hybrid_conditions(root)
            self.edit({'report_path':conditions[0]['report_paths'][1]},
                      lambda r:r['chunks'][0]['voice_reference_request'].update(instructions='Different request.'))
            with self.assertRaisesRegex(ValueError,'声音档案版本'):
                prepare_listening(conditions,root/'pack')

    def test_hybrid_incomplete_or_contradictory_routes_are_rejected(self):
        mutations = [lambda c:c.pop('voice_reference_request'),
                     lambda c:c['voice_reference_request'].update(model='mimo-v2.5-tts'),
                     lambda c:c['voice_reference_request'].update(voice_version='other'),
                     lambda c:c['voice_reference_request'].update(language='zh'),
                     lambda c:c['chunk']['profile'].pop('voice_description')]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); conditions = self.hybrid_conditions(root)
                self.edit({'report_path':conditions[0]['report_paths'][1]}, lambda r:mutate(r['chunks'][0]))
                with self.assertRaises(ValueError):prepare_listening(conditions,root/'pack')
                self.assertFalse((root/'pack').exists())

    def test_clone_reference_copies_match_by_content_and_mutation_is_rejected(self):
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); conditions = self.hybrid_conditions(root)
                reference = root/'clone_reference.wav'; duplicate = root/'copy.wav'
                duplicate.write_bytes(reference.read_bytes())
                # 场景2的Alice是最后一句。
                def update(report):
                    item = report['chunks'][3]
                    item['chunk']['profile']['reference_audio_path'] = str(duplicate)
                    item['voice_reference_request']['reference_audio_path'] = str(duplicate)
                self.edit({'report_path':conditions[0]['report_paths'][1]},update)
                if corrupt:
                    data, rate = sf.read(duplicate,dtype='int16'); data[0] += 1
                    sf.write(duplicate,data,rate,subtype='PCM_16')
                    with self.assertRaisesRegex(ValueError,'指纹不符'):
                        prepare_listening(conditions,root/'pack')
                    self.assertFalse((root/'pack').exists())
                else:self.assertEqual(prepare_listening(conditions,root/'pack')['trials'],16)

    def test_single_scene_with_profiles_checks_same_role_identity_too(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); conditions = self.conditions(root)
            def update(report):
                for i,item in enumerate(report['chunks']):
                    item['chunk']['profile'] = {'voice':'Mia','voice_version':'v2' if i == 2 else 'v1'}
            self.edit(conditions[0],update)
            with self.assertRaisesRegex(ValueError,'声音档案版本'):
                prepare_listening(conditions,root/'pack')
            self.assertFalse((root/'pack').exists())

    def test_duplicate_audio_cannot_count_as_independent_role_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conditions = self.conditions(root)
            path = Path(conditions[1]['report_path'])
            report = json.loads(path.read_text())
            chunks = report['chunks']
            Path(chunks[2]['rendered_path']).write_bytes(Path(chunks[0]['rendered_path']).read_bytes())
            report['assembly']['spans'][2]['render_sha256'] = sha(chunks[2]['rendered_path'])
            pcm = path.parent / 'chapter.wav'
            samples = np.concatenate([sf.read(c['rendered_path'], dtype='int16')[0] for c in chunks])
            sf.write(pcm, samples, 16000, subtype='PCM_16')
            final = Path(report['output_file'])
            final.write_bytes(pcm.read_bytes())
            report['final_verification']['metrics'].update(encoded_sha256=sha(final), reference_pcm_sha256=sha(pcm))
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'alice.*至少两个不同'):
                prepare_listening(conditions, root / 'pack')
            self.assertFalse((root / 'pack').exists())

    def test_invalid_scene_lists_and_multiscene_cli(self):
        from audiobook_generator.audio_core.__main__ import main
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conditions = self.multi_scene_conditions(root)
            for paths in ([], 'not-a-list', [None], [conditions[0]['report_paths'][0]] * 2):
                bad = [dict(conditions[0]), dict(conditions[1])]
                bad[0]['report_paths'] = paths
                with self.subTest(paths=paths), self.assertRaises(ValueError):
                    prepare_listening(bad, root / 'bad')
                self.assertFalse((root / 'bad').exists())
            path = root / 'conditions.json'
            path.write_text(json.dumps(conditions))
            with patch('openai.OpenAI') as remote, contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(['prepare-listening', '--conditions', str(path), '--output', str(root / 'cli_pack')])
                remote.assert_not_called()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())['trials'], 16)

    def test_blind_export_keeps_pcm_pending_answers_and_private_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = prepare_listening(self.conditions(root), root / "pack")
            public = root / "pack/public"
            key_path = root / "pack/private_answer_key.json"
            key = json.loads(key_path.read_text())
            payload = json.loads((public / "trials.json").read_text())
            self.assertEqual(result["trials"], 8)
            self.assertEqual(result["requests_sent"], 0)
            self.assertTrue(result["human_review_required"])
            for trial in payload["trials"]:
                self.assertNotIn(trial["audio"], trial["reference_voices"].values())
            for name, expected in key["public_sha256"].items():
                self.assertEqual(sha(public / name), expected)
            self.assertEqual(len(key["sources"]), 2)
            for name in ("trials.json", "README.md", "responses.csv", "index.html"):
                text = (public / name).read_text(encoding="utf-8-sig")
                for private in ("interaction", "random", "alice", "bob", str(root)):
                    self.assertNotIn(private, text)
            self.assertEqual(score_listening(key_path, public / "responses.csv")["conditions"], {})
            with self.assertRaises(ValueError):
                prepare_listening(self.conditions_in_pack(root), root / "pack")

    def conditions_in_pack(self, root):
        return [{"condition": c, "report_path": str(root / c / "quality.json")}
                for c in ("interaction", "random")]

    def test_relocated_reports_use_bound_pcm_and_ignore_unrelated_nearby_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conditions = self.conditions(root)
            copies = root / "reevaluated"
            copies.mkdir()
            sf.write(copies / "chapter.wav", np.zeros(204800), 16000, subtype="PCM_16")
            for condition in conditions:
                path = Path(condition["report_path"])
                data = json.loads(path.read_text())
                data["final_verification"]["metrics"]["reference_pcm_path"] = str(path.parent / "chapter.wav")
                copy = copies / (condition["condition"] + ".json")
                copy.write_text(json.dumps(data))
                condition["report_path"] = str(copy)
            result = prepare_listening(conditions, root / "pack")
            self.assertEqual(result["trials"], 8)
            self.assertEqual(result["requests_sent"], 0)

    def test_declared_reference_must_be_absolute_and_hash_bound_without_fallback(self):
        for declaration in ("chapter.wav", "missing.wav", "other.wav"):
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                conditions = self.conditions(root)
                sf.write(root / "other.wav", np.zeros(204800), 16000, subtype="PCM_16")
                path = declaration if declaration == "chapter.wav" else str(root / declaration)
                self.edit(conditions[1], lambda r: r["final_verification"]["metrics"].update(reference_pcm_path=path))
                with self.assertRaises(ValueError):
                    prepare_listening(conditions, root / "pack")
                self.assertFalse((root / "pack").exists())

    def test_content_signal_boundary_and_encoding_failures_leave_no_partial_pack(self):
        changes = [
            lambda r: r["chunks"][0]["report"]["dimensions"].update(content="incomplete"),
            lambda r: r["chunks"][0]["report"]["issues"].append({"code": "asr_mismatch", "dimension": "content"}),
            lambda r: r["chunks"][0]["report"]["dimensions"].update(signal="incomplete"),
            lambda r: r["chunks"][0]["report"]["dimensions"].update(signal="failed"),
            lambda r: r["boundaries"][0]["issues"].append({"code": "cutoff_suspected", "dimension": "stitching"}),
            lambda r: r.update(boundaries=[]),
            lambda r: r["final_verification"]["dimensions"].update(content="incomplete"),
            lambda r: r["final_verification"]["dimensions"].update(encoding="incomplete"),
            lambda r: r["chunks"][0]["report"]["issues"].append({"code": "speaker_drift", "dimension": "consistency"}),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                conditions = self.conditions(root)
                self.edit(conditions[1], change)
                with self.assertRaises(ValueError):
                    prepare_listening(conditions, root / "pack")
                self.assertFalse((root / "pack").exists())

    def test_actual_chunk_context_and_final_audio_must_match_report(self):
        for target in ("chunk0.wav", "chapter.wav", "final.wav"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                conditions = self.conditions(root)
                sf.write(root / "random" / target, np.zeros(51200 if target.startswith("chunk") else 204800),
                         16000, subtype="PCM_16")
                with self.assertRaises(ValueError):
                    prepare_listening(conditions, root / "pack")
                self.assertFalse((root / "pack").exists())

    def test_matching_hash_does_not_hide_wrong_pcm_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conditions = self.conditions(root)
            pcm = root / "random/chapter.wav"
            sf.write(pcm, np.zeros(204800), 16000, subtype="PCM_16")
            self.edit(conditions[1], lambda r: r["final_verification"]["metrics"].update(reference_pcm_sha256=sha(pcm)))
            with self.assertRaisesRegex(ValueError, "实际 PCM"):
                prepare_listening(conditions, root / "pack")
            self.assertFalse((root / "pack").exists())

    def test_text_mismatch_and_interrupted_copy_do_not_publish_partial_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conditions = self.conditions(root)
            self.edit(conditions[1], lambda r: r["chunks"][0]["chunk"].update(source_text="Changed original."))
            with self.assertRaisesRegex(ValueError, "相同正文"):
                prepare_listening(conditions, root / "pack")
            self.assertFalse((root / "pack").exists())
            self.edit(conditions[1], lambda r: r["chunks"][0]["chunk"].update(source_text="Sentence 0."))
            with patch("audiobook_generator.audio_core.listening.shutil.copyfile", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    prepare_listening(conditions, root / "pack")
            self.assertFalse((root / "pack").exists())

    def test_scoring_and_answer_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepare_listening(self.conditions(root), root / "pack")
            key_path, responses = root / "pack/private_answer_key.json", root / "pack/public/responses.csv"
            key = json.loads(key_path.read_text())
            rows = self.rows(responses)
            row = rows[0]
            answer = key["answers"][row["trial_id"]]
            row.update(participant_id="constructed-listener", response_role=answer["correct_role"])
            self.write_rows(responses, rows)
            result = score_listening(key_path, responses)
            self.assertEqual(result["conditions"][answer["condition"]]["accuracy"], 1)
            self.assertEqual(result["analysis_kind"], "descriptive_pilot")
            for invalid in ([row, row], [{**row, "response_role": "角色999"}],
                            [{"participant_id": "", "trial_id": "unknown", "response_role": ""}]):
                self.write_rows(responses, invalid)
                with self.assertRaises(ValueError):
                    score_listening(key_path, responses)
            responses.write_text("trial_id\nmissing-columns\n")
            with self.assertRaises(ValueError):
                score_listening(key_path, responses)

    def test_scoring_rejects_changed_audio_and_trial_materials(self):
        for target in ("trials.json", "audio", "index.html"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                prepare_listening(self.conditions(root), root / "pack")
                public = root / "pack/public"
                path = next((public / 'audio').glob('*.wav')) if target == 'audio' else public / target
                path.write_bytes(b"altered")
                with self.assertRaisesRegex(ValueError, "试听材料已改变"):
                    score_listening(root / "pack/private_answer_key.json", public / "responses.csv")

    def test_offline_player_whitelists_public_fields_and_escapes_script_boundaries(self):
        import re
        from audiobook_generator.audio_core.listening_player import render_listening_player
        malicious = '</script><img src=x onerror=alert(1)>&\u2028'
        payload = {'secret':'PRIVATE', 'trials':[{'trial_id':'trial1','audio':'audio/target.wav',
            'reference_voices':{malicious:'audio/ref.wav'},'correct_role':'PRIVATE',
            'condition':'PRIVATE','source_role':'PRIVATE'}]}
        page = render_listening_player(payload)
        self.assertNotIn('PRIVATE',page)
        self.assertNotIn(malicious,page)
        data = json.loads(re.search(r'<script id="trial-data" type="application/json">(.*?)</script>',page,re.S).group(1))
        self.assertEqual(data['trials'],[{'trial_id':'trial1','audio':'audio/target.wav',
            'reference_voices':{malicious:'audio/ref.wav'}}])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepare_listening(self.conditions(root),root/'pack')
            public = root/'pack/public'
            key = json.loads((root/'pack/private_answer_key.json').read_text())
            self.assertIn('index.html',key['public_sha256'])
            self.assertEqual(sha(public/'index.html'),key['public_sha256']['index.html'])
            self.assertEqual(score_listening(root/'pack/private_answer_key.json',public/'responses.csv')['conditions'],{})
