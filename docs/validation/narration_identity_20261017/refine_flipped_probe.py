"""在同一次授权的20次总额度内复核三个问题块，保留首轮提议。

只复用首轮模型已有的可定位身份线索，不新建整章分析或索引请求。
默认仅显示计划；--execute 才发请求。所有正文／响应仍写入忽略目录。
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    folder = Path(__file__).parent
    plan = json.loads((folder / 'flipped_probe_plan.json').read_text())
    destination = Path(plan['result_directory'])
    records = json.loads((destination / 'requests.json').read_text())
    targets = [(5, 1), (5, 3), (6, 3)]
    if not args.execute:
        print(json.dumps({'targets': targets, 'used_requests': len(records),
                          'total_limit': plan['max_requests'], 'new_requests': 0}))
        return
    assert len(records) == 15 and all('round' not in row for row in records), '首轮请求已变化，拒绝重跑'

    import httpx
    from openai import OpenAI
    from audiobook_generator.utils.deepseek_config import get_deepseek_credentials
    from audiobook_generator.ui import web_ui
    from audiobook_generator.role_script import deepseek_splitter as splitter
    from audiobook_generator.role_script.models import RoleScriptV1, ChapterScript
    from audiobook_generator.role_script.project_store import load_project, save_project
    from audiobook_generator.role_script.narration import complete_narration_evidence, ground_narration_segments
    from audiobook_generator.role_script.v2_generation import upgrade_generated_script

    book = Path(plan['book_path'])
    assert hashlib.sha256(book.read_bytes()).hexdigest() == plan['book_sha256']
    chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book), 1, -1, 'auto', 'double', False, False, None)
    for item in plan['chapters']:
        assert hashlib.sha256(chapters[item['chapter_index'] - 1][1].encode()).hexdigest() == item['source_sha256']
    initial = load_project(destination / 'machine_proposal.json', book_sha256=plan['book_sha256'])
    assert initial is not None
    review = destination / 'targeted_review'
    review.mkdir(exist_ok=False)
    (destination / 'initial_requests.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    contexts, parts = {}, {}
    role_metadata = {rid: {'display_name': role.display_name, 'gender': role.gender or 'unknown'}
                     for rid, role in initial.roles.items()}
    known = [{'role_id': rid, **meta} for rid, meta in role_metadata.items() if rid != 'narrator']
    for chapter in initial.chapters:
        source = chapters[chapter.chapter_index - 1][1]
        cursor = 0
        for chunk, part in enumerate(splitter._split_text_chunks(source), 1):
            parts[chapter.chapter_index, chunk] = (cursor, cursor + len(part), part)
            cursor += len(part)
        votes = Counter(s.role_id for s in chapter.segments if s.text_kind == 'narration' and s.role_id != 'narrator')
        assert len(votes) == 1, '已有多个叙述候选，不能用本次单候选诊断'
        rid = next(iter(votes))
        evidence = list(dict.fromkeys(e.quote for s in chapter.segments if s.role_id == rid and s.speaker
                                     for e in s.speaker.evidence if e.kind == 'narrator_identity'
                                     and len(e.quote) <= 400 and source.count(e.quote) == 1))
        assert evidence
        contexts[chapter.chapter_index] = {'known_characters': known, 'chapter_narration': {
            'perspective': 'character', 'basis': 'cached_identity_segments_from_initial_machine_proposal',
            'narrators': [{'role_id': rid, **role_metadata[rid],
                          'evidence': [{'quote': q, 'kind': 'narrator_identity'} for q in evidence[:3]]}]}}
    (review / 'cached_contexts.json').write_text(json.dumps(contexts, ensure_ascii=False, indent=2))
    key, base_url, model = get_deepseek_credentials()
    origin = urlsplit(base_url)
    assert key and origin.scheme == 'https' and origin.hostname
    current = None

    def guard(request):
        target = urlsplit(str(request.url))
        assert request.method == 'POST' and (target.scheme, target.hostname, target.port or 443) == (origin.scheme, origin.hostname, origin.port or 443)
        assert target.path.endswith('/chat/completions') and current in targets
        payload = json.loads(request.content)
        ch, chunk = current
        prompt = payload['messages'][-1]['content']
        assert payload['model'] == model and f'Chapter number: {ch}\n' in prompt
        assert parts[current][2].strip() in prompt
        count = sum(r['chapter'] == ch and r['stage'] == 'split' for r in records)
        chapter_plan = next(item for item in plan['chapters'] if item['chapter_index'] == ch)
        if len(records) >= plan['max_requests'] or count >= chapter_plan['split_requests_max']:
            raise RuntimeError('本次授权文字请求额度已用完')
        records.append({'number': len(records) + 1, 'chapter': ch, 'stage': 'split', 'chunk': chunk,
                        'round': 'targeted_review', 'model': model, 'service_host': origin.hostname,
                        'sent_at': datetime.now(timezone.utc).isoformat()})
        (destination / 'requests.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))

    client = OpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=120,
                    http_client=httpx.Client(follow_redirects=False, event_hooks={'request': [guard]}))
    replacements, failures = {}, []
    pending = targets
    try:
        for attempt in (1, 2):
            retry = []
            for current in pending:
                ch, chunk = current
                print(f'复核第{ch}章第{chunk}块，第{attempt}次；已用{len(records)}/{plan["max_requests"]}次', flush=True)
                try:
                    payload = splitter._request_chunk(client, model, ch, chapters[ch - 1][0],
                        parts[current][2].strip(), 'openai', 'en', narration_context=contexts[ch])
                    (review / f'ch{ch}_chunk{chunk}_attempt{attempt}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
                    raw_roles, raw_segments = splitter._raw_segments(payload)
                    for rid, meta in raw_roles.items():
                        if isinstance(rid, str) and isinstance(meta, dict):
                            role_metadata.setdefault(rid, meta)
                    segments = splitter._reconcile_segments(parts[current][2], raw_segments, role_metadata)
                    covered = ''.join(s.text for s in segments)
                    part = parts[current][2]
                    assert part.endswith(covered) and not part[:len(part) - len(covered)].strip()
                    segments[0] = replace(segments[0], text=part[:len(part) - len(covered)] + segments[0].text)
                    segments = [replace(s, text_kind=s.text_kind or 'unknown') for s in segments]
                    replacements[current] = ground_narration_segments(complete_narration_evidence(
                        segments, chapters[ch - 1][1], contexts[ch]), chapters[ch - 1][1])
                except Exception as exc:
                    failures.append({'chapter': ch, 'chunk': chunk, 'attempt': attempt, 'exception_type': type(exc).__name__})
                    retry.append(current)
                    print(f'该块未完成严格对齐：{type(exc).__name__}；保留首轮结果', flush=True)
            pending = retry
            if not pending:
                break
    finally:
        client.close()

    output = []
    for chapter in initial.chapters:
        result = []
        for chunk in range(1, 4):
            start, end, _ = parts[chapter.chapter_index, chunk]
            key_part = (chapter.chapter_index, chunk)
            if key_part in replacements:
                result.extend(replacements[key_part])
            else:
                for segment in chapter.segments:
                    a, b = max(start, segment.source_span.start), min(end, segment.source_span.end)
                    if a < b:
                        evidence = tuple((e.quote, e.kind) for e in segment.speaker.evidence) if segment.speaker else ()
                        result.append(replace(segment, text=chapters[chapter.chapter_index - 1][1][a:b], evidence_candidates=evidence))
        assert ''.join(s.text for s in result) == chapters[chapter.chapter_index - 1][1]
        output.append(ChapterScript(chapter.chapter_index, chapter.title, splitter._merge_adjacent_segments(result)))
    roles = dict(initial.roles)
    for rid, role in splitter._build_role_definitions('openai', role_metadata, language='en').items():
        roles.setdefault(rid, role)
    generated = RoleScriptV1(1, 'openai', plan['book_sha256'], initial.default_pause_after_ms, roles, tuple(output))
    updated = upgrade_generated_script(generated, chapters, dict(initial.entities),
        parser_fingerprint=initial.parser_fingerprint, model=model, previous=initial, registry_complete=False)
    save_project(updated, destination / 'machine_proposal_revised.json')
    summary = {'requests_total': len(records), 'new_requests': len(records) - 15,
               'strictly_aligned_targets': [list(k) for k in replacements], 'failed_attempts': failures,
               'unresolved_targets': [list(k) for k in targets if k not in replacements],
               'context_origin': '首轮已定位的模型身份提议，非新增整章请求；不是盲测',
               'tts_requests': 0, 'modified_existing_projects': False}
    (review / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
