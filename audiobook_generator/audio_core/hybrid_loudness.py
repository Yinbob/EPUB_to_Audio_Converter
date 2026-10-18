"""混合先导的实测整句响度匹配；只衰减、保留时轴，原版不动。"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import numpy as np
import soundfile as sf

from .annotations import _verify_pcm_layout
from .loudness_preview import measure_loudness
from .repair_review import _read_report, _sha
from .store import fingerprint


def prepare_hybrid_loudness(manifest_path, output):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') != 'mimo-hybrid-scenes-v1' or not manifest.get('chapters'):
        raise ValueError('需要已生成的混合场景清单')
    destination = Path(output).resolve()
    if destination.exists():
        raise ValueError('响度副本目录已存在，拒绝覆盖')
    sources, measurements = [], []
    receipts = [json.loads(p.read_text()) for p in (manifest_path.parent/'project'/'requests').glob('*.json')]
    for entry in manifest['chapters']:
        source = _read_report(entry['report'])
        report = source['report']
        _verify_pcm_layout(source['audio'], report['assembly'], report['chunks'])
        if report.get('experiment_conditioning'):
            raise ValueError('不得在已处理副本上叠加响度处理')
        if sf.info(source['audio']).subtype != 'PCM_16':
            raise ValueError('首轮响度处理只接受PCM16')
        rows = []
        for item in report['chunks']:
            if item.get('composition'):
                raise ValueError('首轮响度匹配不支持复合修复块')
            measured = measure_loudness(item['rendered_path'])
            rows.append(measured)
            measurements.append(measured['integrated_lufs'])
        sources.append((source, rows))
    target = min(measurements)
    if max(measurements) - target > 12:
        raise ValueError('响度跨度超过12dB，请先检查异常样本，尚未处理')
    protocol = {'version': 'hybrid-measured-utterance-lufs-v1', 'target_lufs': target,
        'target_policy': 'quietest_measured_utterance_no_amplification', 'max_attenuation_db': 12,
        'scope': 'source_bound_engineering_pilot', 'sample_positions_preserved': True,
        'requests_sent': 0, 'human_verified': False}
    destination.mkdir(parents=True)
    reports, operations = [], []
    for source, measured in sources:
        report = copy.deepcopy(source['report'])
        chapter = report['chapter_index']
        folder = destination/f'chapter_{chapter:02d}'
        folder.mkdir()
        samples, rate = sf.read(source['audio'], dtype='int16', always_2d=True)
        modified = samples.copy()
        for i, (item, span, measure) in enumerate(zip(report['chunks'], report['assembly']['spans'], measured), 1):
            gain_db = min(0., target - measure['integrated_lufs'])
            gain = 10 ** (gain_db / 20)
            start, end = span['start_sample'], span['end_sample']
            modified[start:end] = np.rint(samples[start:end].astype(np.float64)*gain).astype(np.int16)
            audio = folder/f'chunk_{i:02d}.wav'
            sf.write(audio, modified[start:end], rate, subtype='PCM_16')
            operation = {'kind': 'source_measured_constant_utterance_gain', 'chunk_id': item['chunk']['chunk_id'],
                'gain_db': gain_db, 'gain': gain, 'input_loudness': measure,
                'input_path': item['rendered_path'], 'input_sha256': _sha(item['rendered_path']),
                'output_sha256': _sha(audio), 'start_sample': start, 'end_sample': end}
            operations.append(operation)
            item['rendered_path'] = item['selected_rendered_path'] = str(audio)
            item['render_operations'] = item.get('render_operations', []) + [operation]
            span['render_sha256'] = _sha(audio)
            # 兼容本轮早期报告：从实际请求收据恢复完整请求条件，不猜测全局指令。
            if item.get('voice_reference_request') is None:
                candidates = [r for r in receipts if r.get('audio_path') == item['raw_path'] and r.get('run_id') == manifest['run_id']]
                if len(candidates) != 1:
                    raise ValueError('原始音频缺少唯一实际请求收据，不能重建固定参考上下文')
                item['voice_reference_request'] = candidates[0]['request']
        full = folder/'chapter.wav'
        sf.write(full, modified, rate, subtype='PCM_16')
        _verify_pcm_layout(full, report['assembly'], report['chunks'])
        # 清除原版机器结论；新波形必须重新检查，旧人工裁决不迁移。
        for item, span in zip(report['chunks'], report['assembly']['spans']):
            item['report'] = {'scope_id': item['chunk']['chunk_id'], 'status': 'incomplete',
                'dimensions': {k:'incomplete' for k in ('content','signal','consistency')}, 'issues': [],
                'metrics': {'start_seconds': span['start_sample']/rate, 'end_seconds': span['end_sample']/rate}}
        report['output_file'] = str(full)
        report['quality_status'] = 'incomplete'
        report['boundaries'] = [{'scope_id': b['boundary_id'], 'status': 'incomplete',
            'dimensions': {'content': 'incomplete', 'stitching': 'incomplete'}, 'issues': [],
            'metrics': {'start_seconds': b['start_sample']/rate, 'end_seconds': b['end_sample']/rate}}
            for b in report['assembly']['boundaries']]
        report['reading_configuration']['role_references'] = manifest['references']
        report['final_verification'] = {'scope_id': 'final_encoding', 'status': 'incomplete',
            'dimensions': {'encoding':'incomplete', 'content':'incomplete'}, 'issues': [],
            'metrics': {'reference_pcm_path':str(full), 'reference_pcm_sha256':_sha(full)}}
        report['experiment_conditioning'] = {**protocol, 'protocol_sha256':fingerprint(protocol),
            'source_report':source['path'], 'source_report_sha256':source['report_sha256'],
            'quality_pending_reevaluation':True}
        report.pop('human_adjudication', None)
        descriptor = folder/'descriptor.json'
        descriptor.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        reports.append(str(descriptor))
        if _sha(source['path']) != source['report_sha256'] or _sha(source['audio']) != source['encoded_sha256']:
            raise ValueError('处理期间原报告／音频变化')
    result = {'schema_version':'mimo-hybrid-loudness-v1', 'protocol':protocol,
        'source_manifest':str(manifest_path), 'source_sha256':_sha(manifest_path),
        'report_paths':reports, 'operations':operations, 'requests_sent':0}
    (destination/'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return result
