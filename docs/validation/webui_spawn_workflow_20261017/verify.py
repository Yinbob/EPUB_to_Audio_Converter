"""网页函数 → 真实 spawn → SDK 本地替身 → 导出／报告／资源库；禁止外网。"""
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1', MODELSCOPE_OFFLINE='1', GRADIO_ANALYTICS_ENABLED='False')

# 主进程和每层 spawn 都安装同一防线，不读取真实凭证；不是修改用户配置。
import httpx
_send = httpx.Client.send


def local_only_send(self, request, *args, **kwargs):
    endpoint = os.environ.get('BOOK_UI_SMOKE_ENDPOINT', '')
    allowed = httpx.URL(endpoint) if endpoint else None
    if not allowed or request.url.host != '127.0.0.1' or request.url.port != allowed.port:
        raise RuntimeError('工程验证禁止访问模拟服务之外的地址')
    return _send(self, request, *args, **kwargs)


httpx.Client.send = local_only_send
from audiobook_generator.tts_providers import openai_tts_provider


def local_credentials():
    endpoint = os.environ.get('BOOK_UI_SMOKE_ENDPOINT', '')
    if not endpoint.startswith('http://127.0.0.1:'):
        raise RuntimeError('本地模拟地址未设置')
    return 'dummy-offline-smoke', endpoint


openai_tts_provider.get_mimo_credentials = local_credentials
from audiobook_generator.ui import web_ui


def main():
    import numpy as np
    import soundfile as sf
    from ebooklib import epub
    from audiobook_generator.role_script.models import RoleScriptV1, RoleDefinition, ChapterScript, SegmentScript
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from audiobook_generator.ui.role_voices import make_voice_profile
    from audiobook_generator.ui.audio_quality import find_quality_reports, load_quality_report
    from audiobook_generator.ui.library import selection_details, create_archive

    destination = Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix='webui-workflow-') as temporary:
        work = Path(temporary)
        book_path = work/'Test.epub'
        book = epub.EpubBook()
        book.set_identifier('webui-spawn-smoke')
        book.set_title('Temporary workflow test')
        book.set_language('en')
        documents = []
        for index, ordinal in enumerate(('first', 'second', 'third'), 1):
            page = epub.EpubHtml(title=f'Chapter {index}', file_name=f'c{index}.xhtml', lang='en')
            page.content = f'<h1>Chapter {index}</h1><p>The {ordinal} morning was bright.</p><p>Please wait beside the bridge.</p>'
            book.add_item(page)
            documents.append(page)
        book.spine = documents
        book.add_item(epub.EpubNcx())
        epub.write_epub(str(book_path), book)
        catalog = web_ui.read_book_chapters([str(book_path)], 'Mimo', 'auto', 'double', False, False, None)
        chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book_path), 1, -1, 'auto', 'double', False, False, None)
        assert len(catalog[0]['chapters']) == 3
        output = work/'exports'/'Test'
        output.mkdir(parents=True)
        wave = work/'reference.wav'
        # 正弦波只检验文件与请求链路，不是 TTS 质量数据。
        sf.write(wave, .1*np.sin(np.arange(64000)*.1), 16000, subtype='PCM_16')
        clone = make_voice_profile('narrator', 'clone', None, None, str(wave), 'en', 1, '', output)
        guest = make_voice_profile('guest', 'preset', 'Chloe', None, None, 'en', 1, '', output)
        text = chapters[1][1]
        split = text.index('Please')
        script = RoleScriptV1(1, 'openai', hashlib.sha256(book_path.read_bytes()).hexdigest(), 200,
            {'narrator': RoleDefinition('Narrator', clone), 'guest': RoleDefinition('Guest', guest)},
            (ChapterScript(2, chapters[1][0], (SegmentScript('narrator', text[:split]), SegmentScript('guest', text[split:]))),))
        script_path = work/'script.json'
        script_path.write_text(json.dumps(role_script_to_dict(script)))
        rows = web_ui._role_table_rows(script)
        web_ui.get_output_dir = lambda: str(work/'exports')
        confirmed = web_ui.confirm_auto_role_script(str(script_path), rows, 'Mimo', 'wav', 'mp3')
        assert confirmed[0], confirmed
        settings = work/'quality.json'
        settings.write_text(json.dumps({'no_asr': True, 'no_speaker': True, 'tail_repeat_mode': 'off'}))
        requests = []
        fail = [False]
        raw_audio = wave.read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                assert self.path == '/v1/chat/completions'
                assert self.headers['Authorization'] == 'Bearer dummy-offline-smoke'
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                voice = str(payload['audio'].get('voice', ''))
                if voice.startswith('data:audio/'):
                    assert base64.b64decode(voice.split(',', 1)[1]) == raw_audio
                requests.append({'model': payload['model'], 'text': payload['messages'][-1]['content'],
                                 'has_clone_reference': voice.startswith('data:audio/')})
                body = ({'error': {'message': 'intentional local failure', 'type': 'invalid_request_error'}} if fail[0]
                        else {'id': 'local-smoke', 'object': 'chat.completion', 'created': 0,
                              'model': payload['model'], 'choices': [{'index': 0, 'finish_reason': 'stop',
                              'message': {'role': 'assistant', 'audio': {'data': base64.b64encode(raw_audio).decode()}}}]})
                data = json.dumps(body).encode()
                self.send_response(400 if fail[0] else 200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        os.environ['BOOK_UI_SMOKE_ENDPOINT'] = f'http://127.0.0.1:{server.server_port}/v1'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            kwargs = dict.fromkeys(inspect.signature(web_ui.process_form).parameters, None)
            kwargs.update(provider='Mimo', input_file=[str(book_path)], output_dir=str(output), worker_count=1,
                log_level='INFO', output_text=True, preview=False, title_mode='auto', new_line_mode='double',
                chapter_start=1, chapter_end=-1, remove_endnotes=False, remove_reference_numbers=False,
                model='mimo-v2.5-tts', voices='Mia', speed=1, openai_output_format='wav', instructions='', enable_stream=False,
                role_mode=True, role_script_file=str(script_path), role_table=rows, role_split_confirmed=True,
                role_confirmed_signature=confirmed[3], audio_core_enabled=True, audio_core_repair=False,
                audio_core_settings_file=str(settings), chapter_catalog_state=catalog[0],
                chapter_selection_source=catalog[8], chapter_from_name=2, chapter_to_name=2)
            web_ui.webui_log_file = work/'success.log'
            web_ui.process_form(**kwargs)
            proc = web_ui.running_process
            assert proc is not None
            proc.join(55)
            if proc.is_alive():
                web_ui._terminate_running_batch()
                raise AssertionError('生成子进程超时')
            state = json.loads(web_ui.get_progress_info()[0])
            assert state['mode'] == 'finished', (state, web_ui.webui_log_file.read_text())
            files = web_ui.get_files_in_folder('Test')
            audio = [name for name in files if name.endswith('.wav')]
            assert len(audio) == 1 and audio[0].startswith('0002_'), files
            assert len(requests) == 2, requests
            requested_text = ' '.join(r['text'] for r in requests)
            assert 'second morning' in requested_text and 'first morning' not in requested_text and 'third morning' not in requested_text
            assert {r['model'] for r in requests} == {'mimo-v2.5-tts', 'mimo-v2.5-tts-voiceclone'}
            assert sum(r['has_clone_reference'] for r in requests) == 1
            reports = find_quality_reports(output)
            assert len(reports) == 1
            report, issues, _ = load_quality_report(reports[0])
            assert report['chapter_index'] == 2
            assert report['quality_status'] == 'incomplete'
            _, downloads, previews = selection_details(work/'exports', 'Test', audio)
            assert len(downloads) == len(previews) == 1
            archive, count = create_archive(work/'exports', 'Test', audio)
            assert Path(archive).is_file() and count == 1
            (destination/'success.log').write_text(web_ui.webui_log_file.read_text())
            outcome = {'selected_chapters': [2, 2], 'numeric_fallback_snapshot': [1, -1],
                       'request_models': [r['model'] for r in requests], 'success_state': state,
                       'exported_files': files, 'quality_chapter': report['chapter_index'],
                       'quality_status': report['quality_status'], 'download_count': len(downloads),
                       'archive_count': count, 'external_requests': 0, 'audio_kind': 'synthetic tone, not speech'}
            previous_requests = len(requests)
            web_ui.webui_log_file = work/'resume.log'
            web_ui.process_form(**kwargs)
            web_ui.running_process.join(55)
            if web_ui.running_process.is_alive():
                web_ui._terminate_running_batch()
                raise AssertionError('缓存复用分支超时')
            resumed = json.loads(web_ui.get_progress_info()[0])
            assert resumed['mode'] == 'finished', resumed
            assert len(requests) == previous_requests
            assert len(find_quality_reports(output)) == 2
            outcome['resume_new_requests'] = len(requests) - previous_requests
            outcome['resume_state'] = resumed
            (destination/'resume.log').write_text(web_ui.webui_log_file.read_text())
            # 用全新输出目录规避缓存，验证服务失败不会被显示为完成。
            fail[0] = True
            kwargs['output_dir'] = str(work/'failed')
            web_ui.webui_log_file = work/'failure.log'
            web_ui.process_form(**kwargs)
            web_ui.running_process.join(55)
            if web_ui.running_process.is_alive():
                web_ui._terminate_running_batch()
                raise AssertionError('失败分支超时')
            failed_state = json.loads(web_ui.get_progress_info()[0])
            assert failed_state['mode'] == 'failed', failed_state
            outcome['failure_state'] = failed_state
            outcome['failure_exports'] = len(list((work/'failed').glob('*.wav')))
            assert outcome['failure_exports'] == 0
            failure_reports = find_quality_reports(work/'failed')
            assert len(failure_reports) == 1
            failed_report, failure_rows, _ = load_quality_report(failure_reports[0])
            assert failed_report['generation_status'] == 'failed'
            assert any(row[3] == 'failed' for row in failure_rows)
            outcome['failure_report_visible'] = True
            (destination/'failure.log').write_text(web_ui.webui_log_file.read_text())
            (destination/'result.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
            print(json.dumps(outcome, ensure_ascii=False))
        finally:
            if web_ui.running_process and web_ui.running_process.is_alive():
                web_ui._terminate_running_batch()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
