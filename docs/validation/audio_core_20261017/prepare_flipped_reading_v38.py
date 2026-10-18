"""合并本章同角色连续校对段；保留来源及原核验段落映射，不选声或合成。"""
import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
BASE = ROOT / 'audiobook_output/flipped_chapter_pilot_20261017'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise ValueError('拒绝覆盖已有文件：' + path.name)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from audiobook_generator.role_script.validator import validate_role_script
    from audiobook_generator.role_script.models import SynthesisUnit, VoiceProfile, SourceSpan
    from audiobook_generator.audio_core.reading import build_reading_plan

    path = BASE / 'chapter_05.roles.confirmed_unvoiced.json'
    original_hash = sha(path)
    raw = json.loads(path.read_text())
    # 修正上一轮脚本写出的非标准枚举；只修元数据，归属与人工结论保持不变。
    original, before_report = load_role_script(path)
    assert original is None and all(e.code == 'invalid_confidence_kind' for e in before_report.errors)
    for c in raw['chapters']:
        for s in c['segments']:
            assert s['speaker']['confidence_kind'] == 'human_confirmed'
            s['speaker']['confidence_kind'] = 'human'
    corrected_path = BASE / 'chapter_05.roles.confirmed_unvoiced.v38.json'
    save(corrected_path, raw)
    script, reloaded = load_role_script(corrected_path)
    assert script is not None and reloaded.ok, reloaded.to_dict()
    source = json.loads((BASE / 'source_chapters.json').read_text())
    proposal = json.loads((BASE / 'local_role_proposal.json').read_text())
    chapters = [(c['title'], c['text']) for c in source['chapters']]
    chapter = script.chapters[0]
    groups = []
    for segment in chapter.segments:
        assert segment.speaker.status == 'confirmed'
        if groups:
            left = groups[-1][-1]
            same = (left.role_id == segment.role_id and left.tone == segment.tone
                    and left.pause_after_ms is None and left.speaker == segment.speaker
                    and left.source_span.end == segment.source_span.start)
            if same:
                groups[-1].append(segment)
                continue
        groups.append([segment])

    compacted, mapping = [], []
    for index, group in enumerate(groups, 1):
        start, end = group[0].source_span.start, group[-1].source_span.end
        merged = replace(group[0], segment_id=f'flipped_ch05_read{index:03d}',
                         text=''.join(s.text for s in group), source_span=SourceSpan(chapter.chapter_index, start, end),
                         pause_after_ms=group[-1].pause_after_ms)
        compacted.append(merged)
        mapping.append({'reading_segment_id': merged.segment_id, 'role_id': merged.role_id,
            'source_span': asdict(merged.source_span), 'confirmed_segment_ids': [s.segment_id for s in group],
            'quote_ids': [q['quote_id'] for q in proposal['quotes']
                          if start <= q['source_start'] and q['source_end'] <= end]})
    candidate = replace(script, chapters=(replace(chapter, segments=tuple(compacted)),))
    checked = validate_role_script(candidate, expected_book_sha256=source['book_sha256'],
        chapters=chapters, chapter_start=chapter.chapter_index, chapter_end=chapter.chapter_index)
    errors = checked.report.to_dict()['errors']
    assert len(errors) == 5 and all(e['code'] == 'missing_provider_param' for e in errors)
    assert ''.join(s.text for s in compacted) == chapters[chapter.chapter_index - 1][1]
    assert [sid for m in mapping for sid in m['confirmed_segment_ids']] == [s.segment_id for s in chapter.segments]
    assert [qid for m in mapping for qid in m['quote_ids']] == [q['quote_id'] for q in proposal['quotes']]

    def units(items):
        return tuple(SynthesisUnit(f'{chapter.chapter_index}:{i}:{s.role_id}', chapter.chapter_index,
            chapter.title, i, len(items), s.role_id, script.roles[s.role_id].display_name, s.text,
            VoiceProfile(s.role_id, script.roles[s.role_id].display_name, {}), tone=s.tone,
            pause_after_ms=0 if i == len(items) else script.default_pause_after_ms,
            source_span=s.source_span, segment_id=s.segment_id) for i, s in enumerate(items, 1))

    before = build_reading_plan(units(chapter.segments), chunk_chars=300, language='en')
    chunks = build_reading_plan(units(compacted), chunk_chars=300, language='en')
    text = chapters[chapter.chapter_index - 1][1]
    for a, b in zip(chunks, chunks[1:]):
        assert a.source_span['end'] == b.source_span['start']
    for c in chunks:
        assert text[c.source_span['start']:c.source_span['end']] == c.source_text == c.tts_text
    assert chunks[0].source_span['start'] == 0 and chunks[-1].source_span['end'] == len(text)
    assert len(compacted) == 63 and len(chunks) == 104
    destinations = [BASE / 'chapter_05.reading.confirmed_unvoiced.json',
                    BASE / 'reading_segment_mapping_v38.json', BASE / 'reading_dryrun_v38.json']
    assert not any(p.exists() for p in destinations)
    save(destinations[0], role_script_to_dict(candidate))
    loaded_compact, compact_report = load_role_script(destinations[0])
    assert compact_report.ok and loaded_compact == candidate, compact_report.to_dict()
    save(destinations[1], {'schema_version': 'flipped-reading-segment-mapping-v38',
        'confirmed_source': str(corrected_path), 'confirmed_source_sha256': sha(corrected_path),
        'historical_source': str(path), 'historical_source_sha256': original_hash,
        'metadata_correction': {'from': 'human_confirmed', 'to': 'human',
                                'old_reload_errors': before_report.to_dict()},
        'reading_script_sha256': sha(destinations[0]), 'groups': mapping,
        'speaker_decisions_changed': False, 'quote_coverage_exact': True})
    boundaries = [{'boundary_id': f'{a.chunk_id}|{b.chunk_id}', 'left': a.chunk_id,
        'right': b.chunk_id, 'chapter_offset': a.source_span['end'],
        'same_role': a.role_id == b.role_id, 'planned_inserted_pause_ms': a.pause_after_ms,
        'sample_position': None, 'review_status': 'not_generated'} for a, b in zip(chunks, chunks[1:])]
    save(destinations[2], {'schema_version': 'flipped-reading-dryrun-v38', 'status': 'text_only_no_voice_assignment',
        'chunk_chars': 300, 'before': {'units': len(chapter.segments), 'chunks': len(before),
            'inserted_pause_ms': sum(c.pause_after_ms for c in before)},
        'after': {'units': len(compacted), 'chunks': len(chunks),
            'inserted_pause_ms': sum(c.pause_after_ms for c in chunks)},
        'boundaries': boundaries, 'chunks': [asdict(c) for c in chunks],
        'full_validation_report': checked.report.to_dict(), 'saved_file_reload_passed': True,
        'synthesis_ready': False,
        'tts_requests': 0, 'llm_requests': 0, 'original_source_unchanged': sha(path) == original_hash})
    print('通过：75段核验原稿保留；63个朗读单位、104块、103接缝；37处引文映射完整；声音仍待选择。')


if __name__ == '__main__':
    main()
