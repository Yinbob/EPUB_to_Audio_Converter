"""第一章两处节选的独立响度对照，严格保留原始 PCM 时间表。"""
import copy
import statistics
from pathlib import Path
import numpy as np
import soundfile as sf
from flipped_casting_preview_v39 import ROOT, OUTPUT, REVIEW, read, save, sha
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.loudness_preview import measure_loudness


def main():
    review = read(REVIEW / 'review_manifest.json')
    target = round(statistics.median(i['loudness']['integrated_lufs'] for i in review['items']
                                    if i['role_id'] == 'narrator' and 'scene' in i), 2)
    out = REVIEW / 'loudness_comparison'
    assert not out.exists()
    out.mkdir()
    manifest = {'version': 'flipped-source-specific-loudness-v40', 'target_lufs': target,
        'target_basis': 'median_of_four_current_Bryce_narration_chunks', 'operation': 'attenuation_only',
        'automatically_applied_to_production': False, 'requests_sent': 0, 'human_preference': None,
        'onset_fade_applied': False, 'scenes': []}
    for scene in review['scenes']:
        source = read(Path(scene['report_path']))
        original = Path(source['output_file'])
        _verify_pcm_layout(original, source['assembly'], source['chunks'])
        full, rate = sf.read(original, dtype='int16', always_2d=True)
        modified = full.copy()
        items, mapping, operations = copy.deepcopy(source['chunks']), copy.deepcopy(source['assembly']), []
        for i, (item, span, old) in enumerate(zip(items, mapping['spans'], scene['chunks']), 1):
            gain_db = min(0., target - old['loudness']['integrated_lufs'])
            gain = 10 ** (gain_db / 20)
            start, end = span['start_sample'], span['end_sample']
            candidate = np.rint(full[start:end].astype(np.float64) * gain).astype(np.int16)
            modified[start:end] = candidate
            path = out / f"{scene['sample_id']}_{i:02d}.wav"
            sf.write(path, candidate, rate, subtype='PCM_16')
            item['rendered_path'] = str(path)
            span['render_sha256'] = sha(path)
            operations.append({'chunk_id': item['chunk']['chunk_id'], 'start_sample': start, 'end_sample': end,
                'gain_db': gain_db, 'gain': gain, 'input_loudness': old['loudness'],
                'output_loudness': measure_loudness(path), 'audio_path': str(path), 'audio_sha256': sha(path)})
        candidate_path = out / (scene['sample_id'] + '_matched.wav')
        sf.write(candidate_path, modified, rate, subtype='PCM_16')
        assert sf.info(candidate_path).frames == sf.info(original).frames
        _verify_pcm_layout(candidate_path, mapping, items)
        for boundary in mapping['boundaries']:
            a, b = boundary['start_sample'], boundary['end_sample']
            assert np.array_equal(full[a:b], modified[a:b])
        assert source['assembly']['boundaries'] == mapping['boundaries']
        manifest['scenes'].append({'sample_id': scene['sample_id'], 'source_report': scene['report_path'],
            'source_audio_sha256': sha(original), 'path': str(candidate_path), 'audio_sha256': sha(candidate_path),
            'assembly': mapping, 'operations': operations, 'pcm_layout_verified': True,
            'silence_positions_unchanged': True, 'duration_seconds': len(full)/rate})
    save(out / 'manifest.json', manifest)
    index = REVIEW / 'index.html'
    content = index.read_text()
    block = '<h2>响度对照版（建议先听，再按需比较原版）</h2><p>仅降低偏响片段，以本次Bryce旁白实测中位数 '
    block += f'{target:.2f} LUFS 为参照。没有提高偏轻片段音量；全部停顿和时长保持原样。是否采用仍待你的试听反馈。</p>'
    for scene in manifest['scenes']:
        block += f"<section><h3>{scene['sample_id']} 响度对照</h3><audio controls preload='none' src='loudness_comparison/{scene['sample_id']}_matched.wav'></audio></section>"
    content = content.replace('<section id=', block + '<section id=', 1)
    index.write_text(content, encoding='utf-8')
    with (REVIEW / 'README.md').open('a') as stream:
        stream.write(f'\n新增响度对照：仅将偏响句子衰减至本次旁白中位数{target:.2f} LUFS附近，较轻句子不放大；时长、接缝位置、静音与语速不变。未自动采用。\n\n')
        for scene in manifest['scenes']:
            stream.write(f"- [{scene['sample_id']} 响度对照版]({scene['path']})\n")
    print(f'两处响度对照已生成，实测参考{target:.2f} LUFS；PCM逐块一致、时长与静音位置核验通过。')


if __name__ == '__main__':
    main()
