"""双视角 EPUB → 真 SDK 本地替身 → 声音设置／持久化 → spawn／导出。

使用自编文本和正弦波，拒绝外网，复用既有核验入口的每层进程凭证隔离。
"""
import base64
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUPPORT = Path(__file__).resolve().parents[1] / 'webui_spawn_workflow_20261017' / 'verify.py'
spec = importlib.util.spec_from_file_location('webui_smoke_support', SUPPORT)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
web_ui = support.web_ui


def main():
    import numpy as np
    import soundfile as sf
    from ebooklib import epub
    from audiobook_generator.role_script.project_store import load_project
    from audiobook_generator.ui.audio_quality import find_quality_reports, load_quality_report
    from audiobook_generator.ui.library import selection_details, create_archive

    destination = Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix='narration-workflow-') as temporary:
        work = Path(temporary)
        root = work / 'exports'
        output = root / 'Perspectives'
        output.mkdir(parents=True)
        book_path = work / 'Perspectives.epub'
        book = epub.EpubBook()
        book.set_identifier('narration-identity-local-test')
        book.set_title('Temporary perspectives')
        book.set_language('en')
        pages = []
        for index, name in enumerate(('Alex', 'Blair', 'Unused'), 1):
            page = epub.EpubHtml(title=f'Viewpoint {index}', file_name=f'c{index}.xhtml', lang='en')
            page.content = (f'<h1>Viewpoint {index}</h1><p>I am {name}. I waited beside the bridge.</p>'
                            '<p>“Please wait,” I said.</p>' if index < 3 else
                            '<h1>Unused</h1><p>UNSELECTED_MARKER must stay local.</p>')
            book.add_item(page)
            pages.append(page)
        book.spine = pages
        book.add_item(epub.EpubNcx())
        epub.write_epub(str(book_path), book)
        web_ui.get_output_dir = lambda: str(root)
        catalog = web_ui.read_book_chapters([str(book_path)], 'Mimo', 'auto', 'double', False, False, None)
        chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book_path), 1, -1, 'auto', 'double', False, False, None)
        assert len(chapters) == 3

        waves = {}
        for frequency in (440, 880):
            buffer = io.BytesIO()
            sf.write(buffer, .1 * np.sin(np.arange(64000) * 2 * np.pi * frequency / 16000),
                     16000, format='WAV', subtype='PCM_16')
            waves[frequency] = buffer.getvalue()
        reference = work / 'reference.wav'
        reference.write_bytes(waves[440])
        requests, errors, progress = [], [], []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    assert self.path == '/v1/chat/completions'
                    assert self.headers['Authorization'] == 'Bearer dummy-offline-smoke'
                    payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if 'audio' in payload:
                        text = payload['messages'][-1]['content']
                        assert 'UNSELECTED_MARKER' not in text
                        voice = payload['audio']['voice']
                        cloned = voice.startswith('data:audio/')
                        if cloned:
                            assert base64.b64decode(voice.split(',', 1)[1]) == waves[440]
                            frequency = 440
                        else:
                            assert voice == 'Chloe', voice
                            frequency = 880
                        requests.append({'stage': 'tts', 'model': payload['model'],
                                         'clone': cloned, 'frequency': frequency, 'text': text})
                        message = {'role': 'assistant', 'audio': {'data': base64.b64encode(waves[frequency]).decode()}}
                    else:
                        prompt = payload['messages'][-1]['content']
                        assert 'UNSELECTED_MARKER' not in prompt
                        match = re.search(r'(?:章节：|Chapter number: )([12])', prompt)
                        assert match, prompt[:200]
                        index = int(match.group(1))
                        name = 'Alex' if index == 1 else 'Blair'
                        role_id = name.lower()
                        quote = f'I am {name}.'
                        system = payload['messages'][0]['content']
                        if '人物索引器' in system:
                            stage = 'registry'
                            result = {'characters': [{'name': name, 'evidence_quote': quote}]}
                        elif '叙述视角分析器' in system:
                            stage = 'perspective'
                            result = {'perspective': 'character', 'narrators': [
                                {'role_id': role_id, 'display_name': name,
                                 'gender': 'male' if index == 1 else 'female',
                                 'evidence': [{'quote': quote, 'kind': 'narrator_identity'}]}]}
                        else:
                            stage = 'segments'
                            source = chapters[index - 1][1]
                            boundary = source.index('“')
                            result = {'roles': {role_id: {'display_name': name,
                                      'gender': 'male' if index == 1 else 'female'}}, 'segments': [
                                {'role_id': role_id, 'text_kind': 'narration', 'text': source[:boundary],
                                 'evidence': [{'quote': quote, 'kind': 'narrator_identity'}]},
                                {'role_id': role_id, 'text_kind': 'dialogue', 'text': source[boundary:]}]}
                        requests.append({'stage': stage, 'chapter': index})
                        message = {'role': 'assistant', 'content': json.dumps(result)}
                    body = {'id': 'local-narration', 'object': 'chat.completion', 'created': 0,
                            'model': payload['model'], 'choices': [{'index': 0, 'finish_reason': 'stop', 'message': message}]}
                    code = 200
                except Exception as exc:
                    errors.append(repr(exc))
                    body, code = {'error': {'message': 'local protocol assertion failed'}}, 500
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        endpoint = f'http://127.0.0.1:{server.server_port}/v1'
        os.environ['BOOK_UI_SMOKE_ENDPOINT'] = endpoint
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = work / 'quality.json'
        settings.write_text(json.dumps({'no_asr': True, 'no_speaker': True, 'tail_repeat_mode': 'off'}))

        def split(index):
            result = web_ui.split_role_script_now([str(book_path)], True, False, 'Mimo', 1, -1,
                'auto', 'double', False, False, None, 'dummy-offline-smoke', endpoint, 'local-deepseek',
                False, catalog[0], catalog[8], index, index,
                lambda value, desc: progress.append({'value': value, 'stage': desc}))
            assert result[7], result[2]
            path = result[0]['value']
            script, report = web_ui._load_uploaded_role_script(path)
            assert report.ok
            return path, script, result[1]['value']

        def convert(start, end, path, rows, signature, log_name):
            kwargs = dict.fromkeys(inspect.signature(web_ui.process_form).parameters, None)
            kwargs.update(provider='Mimo', input_file=[str(book_path)], output_dir=str(output), worker_count=1,
                log_level='INFO', output_text=True, preview=False, title_mode='auto', new_line_mode='double',
                chapter_start=1, chapter_end=-1, remove_endnotes=False, remove_reference_numbers=False,
                model='mimo-v2.5-tts', voices='Mia', speed=1, openai_output_format='wav', instructions='', enable_stream=False,
                role_mode=True, role_script_file=path, role_table=rows, role_split_confirmed=True,
                role_confirmed_signature=signature, audio_core_enabled=True, audio_core_repair=False,
                audio_core_settings_file=str(settings), chapter_catalog_state=catalog[0],
                chapter_selection_source=catalog[8], chapter_from_name=start, chapter_to_name=end)
            web_ui.webui_log_file = work / log_name
            web_ui.process_form(**kwargs)
            proc = web_ui.running_process
            assert proc is not None
            proc.join(55)
            if proc.is_alive():
                web_ui._terminate_running_batch()
                raise AssertionError('本地生成进程超时')
            state = json.loads(web_ui.get_progress_info()[0])
            (destination / log_name).write_text(web_ui.webui_log_file.read_text())
            assert state['mode'] == 'finished', state
            assert not errors, errors
            return state

        try:
            path, first, rows = split(1)
            alex_id = next(role_id for role_id, role in first.roles.items() if role.display_name == 'Alex')
            rows, status = web_ui.apply_role_voice_settings(path, rows, alex_id, 'clone', None, None,
                str(reference), 'en', 1, '')
            assert isinstance(rows, list), status
            assigned = web_ui.apply_chapter_narration(path, rows, 1, alex_id)
            assert '已保存' in assigned[1] and not assigned[2], assigned
            rows = assigned[0]['value']
            reviewed, report = web_ui._load_uploaded_role_script(path)
            assert report.ok and reviewed.chapters[0].segments[0].speaker.confidence_kind == 'human'
            confirmed = web_ui.confirm_auto_role_script(path, rows, 'Mimo', 'wav', 'mp3')
            assert confirmed[0], confirmed
            convert(1, 1, path, rows, confirmed[3], 'first_chapter.log')
            assert sum(r['stage'] == 'tts' for r in requests) == 2
            assert all(r['clone'] for r in requests if r['stage'] == 'tts')

            path, combined, rows = split(2)
            assert [c.chapter_index for c in combined.chapters] == [1, 2]
            assert combined.roles[alex_id].provider_params['voice_mode'] == 'clone'
            blair_id = next(role_id for role_id, role in combined.roles.items() if role.display_name == 'Blair')
            assert alex_id != blair_id
            assert all(s.role_id == alex_id for s in combined.chapters[0].segments)
            assert all(s.role_id == blair_id for s in combined.chapters[1].segments)
            confirmed = web_ui.confirm_auto_role_script(path, rows, 'Mimo', 'wav', 'mp3')
            assert confirmed[0], confirmed
            saved = load_project(path, book_sha256=combined.book_sha256)
            assert [s.text_kind for s in saved.chapters[0].segments] == ['narration', 'dialogue']
            state = convert(1, 2, path, rows, confirmed[3], 'two_chapters.log')
            tts = [r for r in requests if r['stage'] == 'tts']
            assert len(tts) == 4 and [r['clone'] for r in tts] == [True, True, False, False], tts
            files = web_ui.get_files_in_folder('Perspectives')
            audio = sorted(name for name in files if name.endswith('.wav'))
            assert len(audio) == 2 and not any(name.startswith('0003_') for name in files), files
            peaks = []
            for name, expected in zip(audio, [440, 880]):
                samples, rate = sf.read(output / name)
                if samples.ndim == 2:
                    samples = samples.mean(axis=1)
                frequencies = np.fft.rfftfreq(len(samples), 1 / rate)
                peak = float(frequencies[np.argmax(np.abs(np.fft.rfft(samples)))])
                assert abs(peak - expected) < 2, (name, peak)
                peaks.append(round(peak, 2))
            reports = find_quality_reports(output)
            assert len(reports) == 3
            for report_path in reports:
                report, _, _ = load_quality_report(report_path)
                assert report['quality_status'] == 'incomplete'
                expected_id = alex_id if report['chapter_index'] == 1 else blair_id
                reading = json.loads(Path(report_path).with_name('reading_plan.json').read_text())
                assert all(chunk['role_id'] == expected_id for chunk in reading['chunks'])
            _, downloads, previews = selection_details(root, 'Perspectives', audio)
            archive, count = create_archive(root, 'Perspectives', audio)
            assert len(downloads) == len(previews) == count == 2 and Path(archive).is_file()
            previous = len(requests)
            convert(1, 2, path, rows, confirmed[3], 'cached_chapters.log')
            assert len(requests) == previous
            outcome = {'selected_chapters': [1, 2], 'never_sent_chapter': 3,
                       'deepseek_requests': [r for r in requests if r['stage'] != 'tts'],
                       'tts_requests': tts, 'generation_state': state, 'exported_files': files,
                       'narration_and_dialogue_share_role': True, 'alex_clone_preserved_on_extension': True,
                       'manual_narration_assignment_saved': True,
                       'artifact_frequency_hz': peaks, 'cache_rerun_new_requests': len(requests) - previous,
                       'download_count': count, 'quality_status': 'incomplete',
                       'audio_kind': 'synthetic tones, not speech', 'external_requests': 0,
                       'progress_stages': progress}
            (destination / 'workflow_result.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
            print(json.dumps(outcome, ensure_ascii=False))
        finally:
            if web_ui.running_process and web_ui.running_process.is_alive():
                web_ui._terminate_running_batch()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
