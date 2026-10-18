"""离线核对授权探针；不请求模型，不修改机器提议或既有项目。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    version = parser.add_mutually_exclusive_group()
    version.add_argument('--revised', action='store_true')
    version.add_argument('--final', action='store_true')
    args = parser.parse_args()
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.validator import validate_role_script
    from audiobook_generator.ui import web_ui

    folder = Path(__file__).parent
    plan = json.loads((folder / 'flipped_probe_plan.json').read_text())
    destination = Path(plan['result_directory'])
    source_path = destination / ('machine_proposal_final.json' if args.final else (
        'machine_proposal_revised.json' if args.revised else 'machine_proposal.json'))
    script, report = load_role_script(source_path)
    assert report.ok and script is not None, '机器提议尚不存在或无法读取'
    book = Path(plan['book_path'])
    assert hashlib.sha256(book.read_bytes()).hexdigest() == plan['book_sha256']
    chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book), 1, -1, 'auto', 'double', False, False, None)
    for item in plan['chapters']:
        body = chapters[item['chapter_index'] - 1][1]
        assert hashlib.sha256(body.encode()).hexdigest() == item['source_sha256']
    checked = validate_role_script(script, chapters=chapters,
        expected_book_sha256=plan['book_sha256'], chapter_start=5, chapter_end=6)
    assert checked.ok, '正式原文覆盖和声音配置校验失败'
    assert [c.chapter_index for c in script.chapters] == [5, 6]
    request_path = destination / 'requests.json'
    if not (args.revised or args.final) and (destination / 'initial_requests.json').exists():
        request_path = destination / 'initial_requests.json'
    requests = json.loads(request_path.read_text())
    if args.revised:
        requests = [r for r in requests if r.get('round') != 'opening_type_classification']
    assert len(requests) <= plan['max_requests']
    counts = Counter((r['chapter'], r['stage']) for r in requests)
    for item in plan['chapters']:
        for stage, field in [('index', 'index_requests'), ('narration', 'narration_requests'), ('split', 'split_requests_max')]:
            assert counts[item['chapter_index'], stage] <= item[field]
    assert all(r['chapter'] in (5, 6) for r in requests)
    baseline, baseline_report = load_role_script(destination / 'machine_proposal.json')
    assert baseline_report.ok and baseline is not None
    original_chapters = {c.chapter_index: c for c in baseline.chapters}
    results = []
    for chapter in script.chapters:
        source = chapters[chapter.chapter_index - 1][1]
        assert ''.join(s.text for s in chapter.segments) == source
        expected = {'bryce'} if chapter.chapter_index == 5 else {'juli', 'julianna'}
        used_ids = {s.role_id for s in chapter.segments}
        matching = {rid for rid, role in script.roles.items()
                    if rid in used_ids and set(re.findall(r'[a-z]+', role.display_name.lower())) & expected}
        kinds, narrators, unexpected = Counter(), Counter(), []
        unclassified_voices = Counter()
        identities = Counter()
        for segment in chapter.segments:
            kinds[segment.text_kind or 'legacy'] += len(segment.text)
            span = segment.source_span
            assert span and source[span.start:span.end] == segment.text
            if segment.text_kind in (None, 'unknown'):
                unclassified_voices[script.roles[segment.role_id].display_name] += len(segment.text)
            if segment.text_kind == 'narration':
                narrators[script.roles[segment.role_id].display_name] += len(segment.text)
                if segment.role_id not in matching:
                    unexpected.append(segment.segment_id)
                identities['with_identity_evidence' if segment.speaker and any(
                    e.kind == 'narrator_identity' for e in segment.speaker.evidence) else 'without_identity_evidence'] += 1
        common = {s.role_id for s in chapter.segments if s.text_kind == 'narration'} & {
            s.role_id for s in chapter.segments if s.text_kind == 'dialogue'} & matching
        frozen_narration_voices = Counter()
        dialogue_voice_changes = 0
        for old in original_chapters[chapter.chapter_index].segments:
            for new in chapter.segments:
                overlap = min(old.source_span.end, new.source_span.end) - max(old.source_span.start, new.source_span.start)
                if overlap > 0:
                    if old.text_kind == 'narration':
                        frozen_narration_voices[script.roles[new.role_id].display_name] += overlap
                    elif old.text_kind == 'dialogue' and new.role_id != old.role_id:
                        dialogue_voice_changes += overlap
        results.append({'chapter': chapter.chapter_index, 'title': chapter.title,
            'expected_viewpoint_from_user': 'Bryce' if chapter.chapter_index == 5 else 'Juli',
            'segment_count': len(chapter.segments), 'exact_source_coverage': True,
            'source_characters_by_kind': dict(kinds), 'narration_characters_by_voice': dict(narrators),
            'unclassified_characters_by_voice': dict(unclassified_voices),
            'frozen_initial_narration_spans_characters_by_voice': dict(frozen_narration_voices),
            'initial_dialogue_reassigned_characters': dialogue_voice_changes,
            'unexpected_narration_segment_ids': unexpected, 'identity_evidence_segment_counts': dict(identities),
            'expected_person_shared_narration_dialogue_role_ids': sorted(common),
            'expected_person_voice_profile_ids': sorted({script.entities[rid].voice_profile_id for rid in matching
                                                        if rid in script.entities and script.entities[rid].voice_profile_id})})
    audit = {'actual_text_requests': len(requests), 'requests_by_chapter_stage': [
        {'chapter': ch, 'stage': stage, 'count': n} for (ch, stage), n in sorted(counts.items())],
        'only_authorized_chapters': True, 'tts_requests': 0,
        'chapters': results, 'machine_proposal_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'scope': '真实模型输出与用户指定整章视角的一致性及工程校验；不等于逐段人工标注准确率或声音听感验收'}
    if args.final:
        from audiobook_generator.role_script.review import assign_chapter_narrator
        first = next(c for c in script.chapters if c.chapter_index == 5)
        second = next(c for c in script.chapters if c.chapter_index == 6)
        other = next(s.role_id for s in second.segments if s.text_kind == 'narration')
        updated, changed = assign_chapter_narrator(script, 5, other)
        result = next(c for c in updated.chapters if c.chapter_index == 5)
        assert changed == sum(s.text_kind == 'narration' for s in first.segments)
        assert result.segments[0].text_kind == 'narration' and result.segments[0].role_id == other
        assert all(s.role_id == other for s in result.segments if s.text_kind == 'narration')
        assert [s for s in first.segments if s.text_kind == 'dialogue'] == [s for s in result.segments if s.text_kind == 'dialogue']
        assert next(c for c in updated.chapters if c.chapter_index == 6) == second
        assert script.roles == updated.roles and script.entities == updated.entities
        audit['chapter_narrator_override_includes_opening'] = True
        audit['override_check_saved_to_project'] = False
    filename = ('flipped_probe_final_audit.json' if args.final else
                'flipped_probe_revised_audit.json' if args.revised else 'flipped_probe_audit.json')
    (folder / filename).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
