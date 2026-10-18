"""保存本次明确反馈，生成来源绑定的首章剧本和独立声音候选夹具。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
BASE = ROOT / 'audiobook_output/flipped_chapter_pilot_20261017'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    if path.exists():
        if json.loads(path.read_text()) == data:
            return
        raise ValueError(f'拒绝覆盖已有记录：{path.name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    from audiobook_generator.role_script.models import (RoleDefinition, CharacterEntity, AliasRecord,
        ChapterScript, SegmentScript, SpeakerDecision, SourceSpan, RoleScriptV2, RoleScriptV1)
    from audiobook_generator.role_script.validator import validate_role_script
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from audiobook_generator.role_script.project_store import parser_fingerprint
    from audiobook_generator.audio_core.store import fingerprint
    from audiobook_generator.audio_core.hybrid_probe import PROMPTS

    source = json.loads((BASE / 'source_chapters.json').read_text())
    proposal_path = BASE / 'local_role_proposal.json'
    proposal = json.loads(proposal_path.read_text())
    chapter = source['selected_conversion_chapter']
    chapters = [(c['title'], c['text']) for c in source['chapters']]
    text = chapters[chapter - 1][1]
    assert digest(Path(source['book_path'])) == source['book_sha256']
    assert hashlib.sha256(text.encode()).hexdigest() == proposal['source_text_sha256']
    review = {
        'schema_version': 'flipped-chapter-human-confirmation-v37',
        'date': '2026-10-17', 'source': 'explicit_user_reply',
        'proposal_path': str(proposal_path), 'proposal_sha256': digest(proposal_path),
        'book_sha256': source['book_sha256'], 'chapter_index': chapter,
        'quote_ids': [q['quote_id'] for q in proposal['quotes']],
        'user_reply': '保留本章角色草稿及上述处理',
        'confirmed': ['37处归属', 'Bryce叙述及本人对白共用声音',
                      'Juli与Julianna为同一人', '概括性短语引用由叙述者朗读'],
        'voice_assignments_confirmed': False, 'full_book_registry_confirmed': False,
        'external_transfer_consent': {
            'destination': 'configured DeepSeek API', 'scope': 'Diving Under only',
            'max_requests': 6, 'user_reply': '允许，仅发送这一章用于角色拆分'},
    }
    save(BASE / 'human_role_confirmation_v37.json', review)
    roles = {r: RoleDefinition(name) for r, name in proposal['roles'].items()}
    aliases = tuple(AliasRecord(name, status='confirmed', source_span=SourceSpan(
        chapter, text.index(name), text.index(name) + len(name)))
        for name in ('Juli', 'Julianna Baker'))
    entities = {r: CharacterEntity(name, aliases=aliases if r == 'juli' else (),
                                 voice_profile_id='flipped_' + r)
                for r, name in proposal['roles'].items()}
    segments = tuple(SegmentScript(s['role_id'], s['text'],
        segment_id=f'flipped_ch05_s{i:03d}',
        source_span=SourceSpan(chapter, s['source_start'], s['source_end']),
        speaker=SpeakerDecision(s['role_id'], 'confirmed', confidence_kind='human'))
        for i, s in enumerate(proposal['segments'], 1))
    script = RoleScriptV2(2, 'openai', source['book_sha256'], 200, roles,
        (ChapterScript(chapter, chapters[chapter - 1][0], segments),), entities,
        parser_fingerprint(source['parser_settings']), {chapter: proposal['source_text_sha256']}, False)
    checked = validate_role_script(script, expected_book_sha256=source['book_sha256'],
        chapters=chapters, chapter_start=chapter, chapter_end=chapter)
    # 尚未选择声音时不伪填默认音色；完整校验应且只应报告五个缺少voice。
    report = checked.report.to_dict()
    assert len(report['errors']) == len(roles), report
    assert all(e['code'] == 'missing_provider_param' and e['path'].endswith('.voice')
               for e in report['errors']), report
    assert ''.join(s.text for s in segments) == text
    save(BASE / 'chapter_05.roles.confirmed_unvoiced.json', role_script_to_dict(script))
    save(BASE / 'confirmed_validation_v37.json', {
        'report': report, 'expected_missing_voice_errors': len(roles), 'source_coverage_exact': True,
        'characters': len(text), 'segments': len(segments), 'quotes': len(review['quote_ids']),
        'roles': len(roles), 'registry_complete': False, 'synthesis_ready': False,
        'reason': '角色归属已确认，声音尚未全部选定；空参数不得直接作为正式合成配置',
        'chapter_local_narrator_identity': 'Bryce',
        'future_pov_policy': '后续章节需独立识别叙述视角，不能把全书narrator固定成Bryce',
    })

    dean = ROOT / 'listening_review/mimo_dean_20261017'
    pending = json.loads((dean / 'reviews.pending.json').read_text())
    save(dean / 'human_acceptance_v37.json', {
        'schema_version': 'mimo-dean-human-review-v37', 'date': '2026-10-17',
        'source': 'explicit_user_reply', 'user_reply': '内容正常，但不适合Bryce',
        'samples': [{**p, 'content_complete': True, 'bryce_voice_suitable': False,
                     'same_voice_consistent': None,
                     'notes': '内容正常包括D02所问词尾；一致性未另行明确，保持空值。'} for p in pending],
        'machine_report_unchanged': True, 'added_to_voice_bank': False,
        'production_reference_created': False,
    })

    descriptions = {
        'bryce_a': 'A youthful male voice in the early teenage range, light and clear in the upper middle register. '
            'A smooth, clean texture with a little natural breath, relaxed forward resonance, and a neutral American English accent. '
            'The identity sounds like an adolescent boy telling his own story, with crisp consonants and natural vowels.',
        'bryce_b': 'A youthful male voice in the teenage range, clear and bright in the middle register. '
            'A slightly dry, lightly textured timbre with compact resonance, easy conversational articulation, '
            'and a neutral American English accent. The identity sounds like an adolescent boy with a gently grounded, unforced voice.',
    }
    candidates = {}
    for role, description in descriptions.items():
        params = {'voice_mode': 'design', 'voice_language': 'en', 'voice_description': description,
                  'instructions': 'Use a steady, moderate audiobook pace and natural conversational phrasing. '
                      'Keep the same voice identity across every passage. Do not exaggerate the character or act out different ages.'}
        params['voice_version'] = fingerprint(params)
        params['voice_profile_id'] = 'flipped_' + role + '_candidate_v1'
        candidates[role] = RoleDefinition('Bryce候选' + role[-1].upper(), params)
    fixture = RoleScriptV1(1, 'openai', fingerprint(PROMPTS), 200, candidates,
        (ChapterScript(1, 'Self-authored common probe fixture',
                       tuple(SegmentScript(r, PROMPTS[0]) for r in candidates)),))
    assert validate_role_script(fixture).ok
    save(BASE / 'bryce_voice_candidates.v1.json', role_script_to_dict(fixture))
    save(BASE / 'bryce_voice_candidate_plan_v37.json', {
        'purpose': '同一角色的两个候选身份，不是两名书中人物',
        'script_scope': 'self_authored_common_probe_fixture_not_book_text',
        'source': 'agent_authored_fixed_voice_descriptions', 'human_suitable': None,
        'samples_per_candidate': 3, 'max_tts_requests': 6, 'request_characters': 520,
        'automatic_repairs': False, 'reason': 'Milo内容异常；Dean已被用户判为不适合Bryce',
        'fallback_policy': '主角色优先内置，但没有合格适配声音时先验证固定描述候选，不强制占用不适配声音',
        'whole_chapter_tts_started': False,
    })
    print('角色确认剧本及两名候选夹具完成：75段、37处引文、5角色，声音未锁定。')


if __name__ == '__main__':
    main()
