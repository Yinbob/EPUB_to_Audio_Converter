"""在原授权总额度内，仅请求一次来核对首章漏返类型的659字符。

默认零请求。保留首轮／修订候选，类型与人物均明确且严格覆盖时另存最终候选。
"""
import argparse
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
    if not args.execute:
        print(json.dumps({'chapter': 5, 'source_characters': 659, 'requests_used': len(records),
                          'total_limit': plan['max_requests'], 'new_requests': 0}))
        return
    assert len(records) == 18, '请求状态已变化，拒绝重复执行'
    output = destination / 'opening_classification'
    output.mkdir(exist_ok=False)

    import httpx
    from openai import OpenAI
    from audiobook_generator.ui import web_ui
    from audiobook_generator.utils.deepseek_config import get_deepseek_credentials
    from audiobook_generator.role_script import deepseek_splitter as splitter
    from audiobook_generator.role_script.models import RoleScriptV1, ChapterScript
    from audiobook_generator.role_script.project_store import load_project, save_project
    from audiobook_generator.role_script.v2_generation import upgrade_generated_script
    from audiobook_generator.role_script.narration import complete_narration_evidence, ground_narration_segments

    book = Path(plan['book_path'])
    assert hashlib.sha256(book.read_bytes()).hexdigest() == plan['book_sha256']
    chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book), 1, -1, 'auto', 'double', False, False, None)
    assert hashlib.sha256(chapters[4][1].encode()).hexdigest() == plan['chapters'][0]['source_sha256']
    prior = load_project(destination / 'machine_proposal_revised.json', book_sha256=plan['book_sha256'])
    assert prior is not None
    first = next(c for c in prior.chapters if c.chapter_index == 5)
    pending = [s for s in first.segments if s.text_kind == 'unknown']
    assert len(pending) == 1
    target_segment = pending[0]
    assert target_segment.source_span.start == 0 and target_segment.source_span.end == 659
    assert chapters[4][1][:659] == target_segment.text
    context = json.loads((destination / 'targeted_review/cached_contexts.json').read_text())['5']
    key, base_url, model = get_deepseek_credentials()
    origin = urlsplit(base_url)
    assert key and origin.scheme == 'https' and origin.hostname
    sent = False

    def guard(request):
        nonlocal sent
        host = urlsplit(str(request.url))
        assert request.method == 'POST' and (host.scheme, host.hostname, host.port or 443) == (origin.scheme, origin.hostname, origin.port or 443)
        assert host.path.endswith('/chat/completions') and not sent
        body = json.loads(request.content)
        prompt = body['messages'][-1]['content']
        assert body['model'] == model and 'Chapter number: 5\n' in prompt and target_segment.text.strip() in prompt
        count = sum(r['chapter'] == 5 and r['stage'] == 'split' for r in records)
        assert len(records) < plan['max_requests'] and count < plan['chapters'][0]['split_requests_max']
        sent = True
        records.append({'number': len(records) + 1, 'chapter': 5, 'stage': 'split',
                        'round': 'opening_type_classification', 'source_start': 0, 'source_end': 659,
                        'model': model, 'service_host': origin.hostname,
                        'sent_at': datetime.now(timezone.utc).isoformat()})
        (destination / 'requests.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))

    with OpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=120,
                http_client=httpx.Client(follow_redirects=False, event_hooks={'request': [guard]})) as client:
        payload = splitter._request_chunk(client, model, 5, first.title, target_segment.text.strip(),
                                         'openai', 'en', narration_context=context)
    (output / 'response.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _raw_roles, raw_segments = splitter._raw_segments(payload)
    roles = {rid: {'display_name': r.display_name, 'gender': r.gender} for rid, r in prior.roles.items()}
    segments = splitter._reconcile_segments(target_segment.text, raw_segments, roles)
    assert all(s.text_kind == 'narration' and s.role_id == target_segment.role_id for s in segments), '类型或人物仍不确定，保留已有提议'
    assert ''.join(s.text for s in segments) == target_segment.text
    segments = ground_narration_segments(complete_narration_evidence(segments, chapters[4][1], context), chapters[4][1])
    assert all(s.role_id == target_segment.role_id for s in segments), '缺少可定位证据，保留已有提议'
    generated_chapters = []
    for chapter in prior.chapters:
        result = []
        for segment in chapter.segments:
            if chapter.chapter_index == 5 and segment.segment_id == target_segment.segment_id:
                result.extend(segments)
            else:
                candidates = tuple((e.quote, e.kind) for e in segment.speaker.evidence) if segment.speaker else ()
                result.append(replace(segment, evidence_candidates=candidates))
        generated_chapters.append(ChapterScript(chapter.chapter_index, chapter.title, tuple(result)))
    generated = RoleScriptV1(1, 'openai', prior.book_sha256, prior.default_pause_after_ms,
                            dict(prior.roles), tuple(generated_chapters))
    final = upgrade_generated_script(generated, chapters, dict(prior.entities),
        parser_fingerprint=prior.parser_fingerprint, model=model, previous=prior, registry_complete=False)
    save_project(final, destination / 'machine_proposal_final.json')
    summary = {'requests_total': len(records), 'new_requests': 1, 'source_characters': 659,
               'type': 'narration', 'voice_identity_unchanged': True,
               'tts_requests': 0, 'modified_existing_projects': False}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
