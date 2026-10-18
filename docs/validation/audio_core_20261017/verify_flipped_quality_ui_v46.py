"""用本机Gradio API验证报告发现、读取、下载与音频试听，不启动合成。"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flipped_casting_preview_v39 import ROOT, read, save, sha


def main():
    import gradio as gr
    from gradio_client import Client
    from audiobook_generator.config.ui_config import UiConfig
    from audiobook_generator.ui import web_ui
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.ui.audio_quality import load_quality_report

    record = read(ROOT / 'docs/validation/audio_core_20261017/flipped_clone_local_repair_v46.json')
    report_path = record['standard_report']; report,_,previews = load_quality_report(report_path)
    output = str(ROOT / 'audiobook_output/flipped_casting_preview_20261017')
    captured = {}
    def capture(self,*args,**kwargs): captured['ui'] = self
    with patch.object(gr.Blocks,'launch',capture):
        web_ui.host_ui(UiConfig(SimpleNamespace(host='127.0.0.1',port=7986)))
    ui = captured['ui']
    result = {'version':'flipped-real-gradio-quality-api-v46','gradio_version':gr.__version__,
        'report_path':report_path,'report_sha256':sha(Path(report_path)),
        'requests_sent':0,'no_browser_visual_review':True,'checks':[]}
    with patch.object(OpenAITTSProvider,'_request_mimo_chunk',side_effect=AssertionError('本检验不允许合成')):
        try:
            ui.launch(server_name='127.0.0.1',server_port=7986,prevent_thread_lock=True,
                inbrowser=False,allowed_paths=[str(ROOT / 'audiobook_output')],quiet=True)
            client = Client('http://127.0.0.1:7986',verbose=False)
            listing = client.predict(output,api_name='/refresh_quality_reports')
            assert report_path in json.dumps(listing)
            result['checks'].append('actual_refresh_callback_discovers_repaired_report')
            shown = client.predict(report_path,api_name='/show_quality_report')
            assert 'incomplete' in shown[0] and '0 次合成请求' in shown[0]
            assert '100 次请求' in shown[0] and '历史记录不全' in shown[0]
            result['checks'].append('actual_show_callback_preserves_pending_and_resource_history')
            downloaded = Path(shown[2])
            assert sha(downloaded) == sha(Path(report_path))
            result['checks'].append('downloaded_report_matches_source_sha256')
            for n in (18,39):
                scope = report['chunks'][n-1]['report']['scope_id']
                audio = client.predict(report_path,scope,api_name='/play_quality_issue')
                if isinstance(audio,dict): audio = audio.get('path')
                assert sha(Path(audio)) == sha(Path(previews[scope]))
            scope = report['boundaries'][75]['scope_id']
            audio = client.predict(report_path,scope,api_name='/play_quality_issue')
            if isinstance(audio,dict): audio = audio.get('path')
            assert sha(Path(audio)) == sha(Path(previews[scope]))
            result['checks'].append('actual_audio_callbacks_return_exact_R018_R039_J076')
        finally:
            ui.close()
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_quality_ui_actual_v46.json',result)
    print(result)


if __name__ == '__main__': main()
