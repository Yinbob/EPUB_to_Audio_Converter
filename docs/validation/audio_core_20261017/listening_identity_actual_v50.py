"""用已有真实混合音频报告核对三种声音模式的身份记录；不推断听感。"""
from collections import Counter, defaultdict
from pathlib import Path

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.listening import _voice_identity


def main():
    v49 = read(ROOT/'docs/validation/audio_core_20261017/asr_adjudication_actual_v49.json')
    hybrid = read(ROOT/'listening_review/hybrid_mixed_20261017/human_acceptance_v34.json')
    paths = [Path(v49['derived_report']['path'])] + [Path(r['quality_report_path']) for r in hybrid['reviews']]
    rows, cross_scene = [], defaultdict(set)
    for number,path in enumerate(paths):
        expected = v49['derived_report']['sha256'] if number == 0 else hybrid['reviews'][number-1]['quality_report_sha256']
        assert sha(path) == expected
        report = read(path)
        identities, modes = defaultdict(set), Counter()
        for item in report['chunks']:
            mode = item['chunk']['profile'].get('voice_mode','preset')
            identity = _voice_identity(item)
            assert identity is not None
            role = item['chunk']['role_id']
            identities[role].add(identity); modes[mode] += 1
            if number:
                cross_scene[role].add(identity)
        assert all(len(v) == 1 for v in identities.values())
        rows.append({'report':str(path), 'report_sha256':expected,
            'chunks':len(report['chunks']), 'mode_counts':dict(modes),
            'identities_per_role':{role:len(values) for role,values in identities.items()},
            'audio_modified':False})
        assert sha(path) == expected
    assert all(len(values) == 1 for values in cross_scene.values())
    log = Path('/tmp/listening_identity_v50_full_release.log')
    assert 'Ran 602 tests' in log.read_text() and 'OK (skipped=30)' in log.read_text()
    save(ROOT/'docs/validation/audio_core_20261017/listening_identity_actual_v50.json',{
        'version':'listening-identity-actual-v50', 'reports':rows,
        'hybrid_cross_scene_identities_per_role':{r:len(v) for r,v in cross_scene.items()},
        'validated_chunks':sum(r['chunks'] for r in rows),
        'claims':'仅核对档案、实际请求、模型路由及克隆参考内容，不证明实际音色稳定或听众收益',
        'tests':{'run':602,'passed':572,'skipped':30,'failures':0,'errors':0,
            'seconds':18.832,'log':str(log),'log_sha256':sha(log),
            'initial_failure_log':'/tmp/listening_identity_v50_full.log',
            'initial_failures':'两次错误明确为音频子进程SIGABRT；另一次候选未选中断言失败的直接原因未确认，原日志保留',
            'affected_three_recheck_log':'/tmp/listening_identity_v50_ffmpeg_recheck.log',
            'affected_three_recheck_passed':True},
        'new_tts_requests':0,'new_llm_requests':0,'overall_project_complete':False,
    })
    print({'validated_chunks':sum(r['chunks'] for r in rows),'cross_scene_roles':len(cross_scene),'requests':0})


if __name__ == '__main__':
    main()
