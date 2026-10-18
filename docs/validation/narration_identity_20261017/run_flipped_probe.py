"""按已准备范围运行真实文字探针；默认仅校验，执行前须取得本轮授权。

不合成语音，不加载／覆盖已有声音项目。原文结果仅写入gitignored输出目录。
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true', help='仅在用户明确授权本计划后使用')
    args = parser.parse_args()
    plan = json.loads(Path(__file__).with_name('flipped_probe_plan.json').read_text())
    book = Path(plan['book_path'])
    assert hashlib.sha256(book.read_bytes()).hexdigest() == plan['book_sha256'], '书籍已变化，需重新准备范围'
    from audiobook_generator.ui import web_ui
    chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book), 1, -1, 'auto', 'double', False, False, None)
    assert [c['chapter_index'] for c in plan['chapters']] == [5, 6], '只允许当前两章计划'
    for item in plan['chapters']:
        title, text = chapters[item['chapter_index'] - 1]
        assert title == item['title'] and len(text) == item['characters']
        assert hashlib.sha256(text.encode()).hexdigest() == item['source_sha256'], '正文解析已变化'
    if not args.execute:
        print(json.dumps({'status': 'scope_verified_no_requests',
                          'chapters': [5, 6], 'max_requests': plan['max_requests']}, ensure_ascii=False))
        return

    import httpx
    from openai import OpenAI
    from audiobook_generator.utils.deepseek_config import get_deepseek_credentials
    from audiobook_generator.role_script import deepseek_splitter as splitter
    from audiobook_generator.role_script.v2_generation import generate_v2_for_book
    from audiobook_generator.role_script.project_store import save_project, parser_fingerprint

    key, base_url, model = get_deepseek_credentials()
    assert key, 'DeepSeek密钥缺失'
    origin = urlsplit(base_url)
    assert origin.scheme == 'https' and origin.hostname, '本探针仅支持已配置的HTTPS服务'
    records, counts = [], Counter()
    allowed = {item['chapter_index']: item for item in plan['chapters']}
    destination = Path(plan['result_directory'])
    destination.mkdir(parents=True, exist_ok=True)
    assert not (destination / 'machine_proposal.json').exists(), '已存在结果，拒绝重复发送；请先检查既有记录'
    assert not (destination / 'requests.json').exists(), '已存在请求记录，拒绝重复发送；请先核对本轮剩余额度'
    limits_hit = []

    def persist_records():
        (destination / 'requests.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))

    def guard(request):
        target = urlsplit(str(request.url))
        assert request.method == 'POST' and (target.scheme, target.hostname, target.port or 443) == (origin.scheme, origin.hostname, origin.port or 443)
        assert target.path.endswith('/chat/completions')
        payload = json.loads(request.content)
        assert payload['model'] == model
        system, prompt = payload['messages'][0]['content'], payload['messages'][-1]['content']
        stage = 'index' if '人物索引器' in system else ('narration' if '叙述视角分析器' in system else 'split')
        match = re.search(r'(?:章节：|章节序号：|Chapter number: )([0-9]+)', prompt)
        assert match and int(match.group(1)) in allowed, '请求不属于已授权章节'
        chapter = int(match.group(1))
        limit_name = {'index': 'index_requests', 'narration': 'narration_requests', 'split': 'split_requests_max'}[stage]
        if len(records) >= plan['max_requests'] or counts[chapter, stage] >= allowed[chapter][limit_name]:
            limits_hit.append({'chapter': chapter, 'stage': stage})
            raise RuntimeError('文字请求达到本轮上限，不再发送')
        counts[chapter, stage] += 1
        records.append({'number': len(records) + 1, 'chapter': chapter, 'stage': stage,
                        'model': model, 'service_host': origin.hostname,
                        'sent_at': datetime.now(timezone.utc).isoformat()})
        persist_records()

    def client_factory(api_key, configured_url):
        assert api_key == key and configured_url == base_url
        # 禁止自动跳转，所有请求均经范围与次数检查；SDK自身不自动重试。
        return OpenAI(api_key=key, base_url=base_url, timeout=120, max_retries=0,
                      http_client=httpx.Client(follow_redirects=False, event_hooks={'request': [guard]}))

    splitter._create_client = client_factory
    fingerprint = parser_fingerprint({'title_mode': 'auto', 'new_line_mode': 'double',
                                      'remove_endnotes': False, 'remove_reference_numbers': False,
                                      'search_and_replace_sha256': None, 'provider': 'openai'})
    try:
        script = generate_v2_for_book(chapters, 5, 6, 'openai', plan['book_sha256'], key, base_url, model,
            parser_fingerprint=fingerprint, index_full_book=False,
            progress=lambda message: print(message, flush=True))
        save_project(script, destination / 'machine_proposal.json')
        ownership = []
        for chapter in script.chapters:
            characters = Counter()
            unknown = 0
            for segment in chapter.segments:
                if segment.text_kind == 'narration':
                    characters[script.roles[segment.role_id].display_name] += len(segment.text)
                elif segment.text_kind in (None, 'unknown'):
                    unknown += len(segment.text)
            ownership.append({'chapter': chapter.chapter_index, 'title': chapter.title,
                              'narration_source_characters_by_voice': dict(characters),
                              'unclassified_source_characters': unknown,
                              'status': 'machine_proposals_not_human_confirmation'})
        summary = {'requests': len(records), 'limits_hit': limits_hit, 'chapters': ownership,
                   'tts_requests': 0, 'modified_existing_projects': False}
        (destination / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False))
    finally:
        persist_records()


if __name__ == '__main__':
    main()
