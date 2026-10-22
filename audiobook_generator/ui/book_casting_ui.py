"""全书自动分配的 Gradio 组件与适配；网络任务不持有项目操作锁。"""
from __future__ import annotations

import time
from pathlib import Path

import gradio as gr

from .book_casting import BookCasting, discover_banks, draft_rows, load_bank, stats_rows
from .role_studio import iter_split_events, render_split_status, SPLIT_ACTIVITY_CSS
from audiobook_generator.role_script.models import RoleScriptV2
from audiobook_generator.role_script.project_store import parser_fingerprint, project_path, save_project
from audiobook_generator.role_script.split_control import controlled_client, current_split_control
from audiobook_generator.utils.deepseek_config import DEFAULT_BASE_URL, DEFAULT_MODEL, get_deepseek_credentials

# 复用已有等待反馈的样式，不另做一套视觉语言。
BOOK_CASTING_CSS = SPLIT_ACTIVITY_CSS.replace('#role_split_status', '#book_casting_activity') + '''
#book_casting { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--apple-border-soft); }
#book_casting_stats, #book_casting_plan { max-width: 100%; min-width: 0; }
#book_casting .table-wrap { overflow-x: auto; }
'''


def activity(state, detail, started):
    value = render_split_status(state, detail, started)
    for old, new in [('等待生成剧本', '等待全书任务'), ('正在准备剧本', '正在准备全书任务'),
                     ('DeepSeek 正在生成剧本', '正在分析全书／准备声音描述'), ('剧本已准备好', '全书任务已完成'),
                     ('剧本未生成成功', '本次任务未完成'), ('已停止拆分', '已停止全书任务')]:
        value = value.replace(old, new)
    value = value.replace('梳理人物', '统计人物').replace('拆分剧本', '分析／选声').replace('保存结果', '保存进度')
    return value


def web():
    from . import web_ui
    return web_ui


def build_book_casting(output_root):
    with gr.Group(elem_id='book_casting') as group:
        gr.HTML('<div class="role-section-title"><h4>全书自动分配</h4><p>先补齐全书分析，再把适合的内置声音优先分给朗读最多的人物。这里只生成文字和配置，不合成音频。</p></div>')
        status = gr.Markdown('先点击「查看统计」检查已分析及尚缺的章节。全书人物索引不等于全书段落分析。', elem_classes='role-caption')
        with gr.Row(elem_classes='role-action-row'):
            refresh = gr.Button('查看统计', elem_classes='btn-ghost', elem_id='book_casting_refresh')
            analyze = gr.Button('分析全书／继续补齐', elem_classes='btn-primary', elem_id='book_casting_analyze')
            stop = gr.Button('停止本次分析／描述', elem_classes='btn-danger', elem_id='book_casting_stop')
        activity = gr.HTML('', elem_id='book_casting_activity')
        stats = gr.Dataframe(headers=['人物编号', '人物', '朗读字／词数', '预计分钟', '出场章数', '最长缺席章数', '待核对段数'],
                             datatype=['str', 'str', 'number', 'number', 'number', 'number', 'number'],
                             value=[], interactive=False, label='全书朗读量（未知归属单列；时间为估算）', elem_id='book_casting_stats')
        with gr.Row():
            language = gr.Dropdown(choices=[('中文', 'zh'), ('英文', 'en')], value='zh', label='本书语言', elem_classes='role-field')
            bank = gr.Dropdown(choices=discover_banks(output_root), label='已核验声音库', elem_classes='role-field')
        with gr.Accordion('导入其他已核验声音库', open=False):
            imported = gr.File(label='声音探针库 JSON（需人工核验、包含至少两条共同探针）', file_types=['.json'], type='filepath')
            gr.Markdown('上传后优先使用导入库。可包含完整 fit_penalties 人工适配表；不会自动扩充或付费建库。', elem_classes='role-caption')
        bank_info = gr.Markdown('请选择声音库，页面将显示实际可用数量。', elem_classes='role-caption')
        make = gr.Button('生成／补齐声音方案', elem_classes='btn-primary', elem_id='book_casting_make')
        plan = gr.Dataframe(headers=['人物编号', '人物', '声音来源', '内置声音', '声音描述（可改）', '朗读要求（可改）', '分配原因'],
                            datatype=['str'] * 7, value=[], interactive=True,
                            label='声音草案：只修改描述和朗读要求；其他声音设置在应用后调整', elem_id='book_casting_plan')
        gr.Markdown('已锁定人物保持原样。可先在表中改描述，再应用到下方人物设置中试听、固定参考音或锁定；最后进入「复核与确认」。归属不会被自动确认。', elem_classes='role-caption')
        apply = gr.Button('将方案应用到角色表', elem_classes='btn-primary', elem_id='book_casting_apply')
        token = gr.State('')
    return locals()


def context(values):
    w = web()
    (book, provider, file_obj, table, title, newline, endnotes, references, replacements, language, bank_path, imported) = values
    if provider != 'Mimo':
        raise ValueError('首版全书自动分配仅支持 MiMo 的单一中文或英文书籍')
    if isinstance(book, (list, tuple)) and len(book) != 1:
        raise ValueError('全书自动分配每次只支持一本书')
    chapters, _, _, book_sha, _ = w._auto_split_chapters(provider, book, 1, None, title, newline, endnotes, references, replacements)
    path = w._role_script_path(file_obj)
    script, report = w._load_uploaded_role_script(file_obj)
    if not report.ok or not isinstance(script, RoleScriptV2) or script.book_sha256 != book_sha:
        raise ValueError('请先载入或生成当前书籍的 V2 角色剧本')
    script = w._apply_role_table(script, table)
    replacement = w._uploaded_file_path(replacements)
    parser_fp = parser_fingerprint({'title_mode': title or 'auto', 'new_line_mode': newline or 'single',
        'remove_endnotes': bool(endnotes), 'remove_reference_numbers': bool(references),
        'search_and_replace_sha256': w._sha256_file_ui(replacement) if replacement else None, 'provider': 'openai'})
    canonical = project_path(w.get_output_dir(), book_sha)
    revision = {'loaded': w._sha256_file_ui(path),
                'canonical': w._sha256_file_ui(canonical) if canonical.is_file() else None}
    from audiobook_generator.audio_core.store import fingerprint
    controller = BookCasting(w.get_output_dir(), chapters, parser_fp, script, source_revision=fingerprint(revision))
    return controller, (w._uploaded_file_path(imported) or bank_path), language, canonical


def status_text(controller, language):
    usage, proof = controller.usage(language)
    pending = sum(r['pending_segments'] for r in usage['roles'].values()) if usage else 0
    unknown = usage['unassigned']['segments'] if usage else 0
    text = (f'已分析 **{len(proof["complete"])}/{proof["total"]} 章** · 尚缺 **{len(proof["missing"])} 章**。'
            f' 待核对归属 {pending} 段，未知归属 {unknown} 段。'
            ' 排名包含人物对白和第一人称自述；缺席章数包含首尾章节，只作参考。')
    if not proof['full_book']:
        text += ' 请点击「分析全书／继续补齐」。不会改变最终生成的章节范围。'
    else:
        text += ' 全书正文覆盖已核对，可以生成声音草案。'
    return text, stats_rows(usage)


def refresh(*values):
    try:
        controller, _, language, _ = context(values)
        text, rows = status_text(controller, language)
        draft = controller.read_draft()
        # 声音库改变后即便正文没变，也不回显旧方案。
        if draft:
            try:
                bank = load_bank(context(values)[1], language)
                from audiobook_generator.audio_core.store import fingerprint
                if draft['bank_sha256'] != fingerprint(bank):
                    draft = None
            except (OSError, ValueError, TypeError):
                draft = None
        return text, rows, draft_rows(draft), draft['draft_id'] if draft else ''
    except Exception as exc:
        return f'尚未统计：{exc}', [], [], ''


def bank_summary(language, selected, imported):
    try:
        path = web()._uploaded_file_path(imported) or selected
        bank = load_bank(path, language)
        return f'本书{ "中文" if language == "zh" else "英文"}可用 **{len(bank["voices"])} 个**已核验内置声音：' + '、'.join(bank['voices']) + '。这不是全部官方声音。'
    except Exception as exc:
        return f'暂无适用声音库：{exc}。请切换语言／声音库，或导入已核验探针库。'


def task(action, *values, request: gr.Request = None):
    w = web()
    base, credentials = values[:12], values[12:15]
    key = None
    delegated = False
    started = time.time() * 1000
    try:
        key = w._begin_role_split(base[0], invalidate_confirmation=False)
        if not key:
            raise ValueError('请先上传一本有效书籍')
        control = w._ROLE_SPLIT_CONTROLS[key]
        control.owner = ('book_casting', request.session_hash if request else None)
        control.task_kind = 'book_casting'
        control.resumable = True

        def run(progress=None):
            controller, bank_path, language, _ = context(base)
            api_key, base_url, model = credentials
            if not api_key:
                default_key, default_url, default_model = get_deepseek_credentials()
                api_key = default_key
                base_url = base_url or default_url
                model = model or default_model
            if action == 'analyze':
                if controller.progress()['missing'] and not (api_key or '').strip():
                    raise ValueError('请先填写 DeepSeek API Key')
                controller.analyze(api_key=api_key, base_url=base_url or DEFAULT_BASE_URL, model=model or DEFAULT_MODEL, progress=progress)
            else:
                bank = load_bank(bank_path, language)
                # 没有缺失描述时不需要请求；使用受控客户端，单次超时且不重试。
                client = controlled_client(api_key, base_url or DEFAULT_BASE_URL)
                controller.make_draft(bank, language, client=client, model=model or DEFAULT_MODEL, progress=progress)
            return refresh(*base)

        delegated = True  # 此后只由实际退出的工作线程释放项目，前端断开也不能提前释放。
        for event in iter_split_events(run, (), control=control, on_finish=lambda: w._end_role_split(key)):
            state = event['state']
            if state == 'result':
                yield (*event['result'], gr.update(value=activity('done', '全书任务已完成；声音合适与否请继续试听。', started)))
            elif state in {'failed', 'cancelled'}:
                # 显示已持久化的章节／成功批次，而不是清空它们。
                result = refresh(*base)
                message = f'{event.get("message", "已停止")} 已完成章节和成功描述批次已保留，再次点击可继续；失败请求不会自动重试。'
                yield (*result, gr.update(value=activity(state, message, started)))
            elif state != 'heartbeat':
                yield (gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.update(value=activity(state, event.get('message', ''), started)))
    except Exception as exc:
        if key and not delegated:
            w._end_role_split(key)
        yield (gr.update(value=f'未开始：{exc}'), gr.skip(), gr.skip(), '', gr.skip())


def stop(book, request: gr.Request = None):
    w = web()
    raw = w._uploaded_file_path(book)
    key = str(project_path(w.get_output_dir(), w._sha256_file_ui(raw)).resolve()) if raw and Path(raw).is_file() else None
    with w._ROLE_SPLIT_LOCK:
        owner = ('book_casting', request.session_hash if request else None)
        control = next((c for c in w._ROLE_SPLIT_CONTROLS.values() if getattr(c, 'owner', None) == owner
                        and getattr(c, 'task_kind', '') == 'book_casting'), None) if request else w._ROLE_SPLIT_CONTROLS.get(key)
        if not control or getattr(control, 'task_kind', '') != 'book_casting':
            return '没有正在运行的全书任务。'
        if getattr(control, 'owner', None) != owner:
            return '此任务由其他网页会话启动，请在启动任务的页面停止。'
        control.cancelled.set()
    return '正在停止；连接退出后可以继续。已完成章节和成功描述批次会保留。'


def apply(*values):
    w = web()
    base, draft_id, edited = values[:12], values[12], values[13]
    try:
        with w._ROLE_SPLIT_LOCK:
            controller, bank_path, language, canonical = context(base)
            if str(canonical.resolve()) in w._ROLE_SPLITTING_PROJECTS or (w.running_process and w.running_process.is_alive()):
                raise ValueError('请等待当前分析或音频生成结束，再应用方案')
            bank = load_bank(bank_path, language)
            result = controller.apply(bank, draft_id, edited)
            save_project(result, canonical)
            w._register_role_script_origin(canonical)
            w._forget_role_confirmation(canonical)
            w._ROLE_RECONFIRM_PROJECTS.add(str(canonical.resolve()))
            message = '已应用全书声音方案。可在下方选人物修改、试听或固定参考音；请到「复核与确认」重新确认后生成。'
            return (str(canonical), w._role_table_rows(result), w._role_choice_update(result), message,
                    False, True, '', w._role_confirmation_probe(False, '', gate=True), w._role_script_summary(result))
    except Exception as exc:
        return (gr.skip(), gr.skip(), gr.skip(), f'未应用：{exc}', gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip())


def wire_book_casting(ui, c):
    base = [c[name] for name in ['input_file', 'provider_state', 'role_script_file', 'role_table', 'title_mode',
            'new_line_mode', 'remove_endnotes', 'remove_reference_numbers', 'search_and_replace_file']]
    base += [ui['language'], ui['bank'], ui['imported']]
    out = [ui['status'], ui['stats'], ui['plan'], ui['token']]
    ui['refresh'].click(refresh, base, out, show_progress='hidden', api_name='book_casting_stats')
    creds = [c[name] for name in ['deepseek_api_key', 'deepseek_base_url', 'deepseek_model']]
    def analyze(*values, request: gr.Request = None):
        yield from task('analyze', *values, request=request)
    def make(*values, request: gr.Request = None):
        yield from task('make', *values, request=request)
    for button, callback, api in [(ui['analyze'], analyze, 'book_casting_analyze'), (ui['make'], make, 'book_casting_make')]:
        button.click(callback, base + creds, out + [ui['activity']], show_progress='hidden', api_name=api,
                     concurrency_id='book-casting-task', concurrency_limit=1)
    ui['stop'].click(stop, c['input_file'], ui['status'], queue=False, show_progress='hidden')
    ui['apply'].click(apply, base + [ui['token'], ui['plan']],
        [c[name] for name in ['role_script_file', 'role_table', 'role_preview_role']] + [ui['status']]
        + [c[name] for name in ['role_split_confirmed', 'role_split_generated', 'role_confirmed_signature',
                               'role_confirmation_probe_host', 'role_verification_summary']],
        show_progress='hidden', api_name='book_casting_apply', concurrency_id='role-project-review', concurrency_limit=1
    ).then(web().load_role_voice_settings,
           [c[name] for name in ['role_script_file', 'role_table', 'role_preview_role']],
           [c[name] for name in ['role_voice_mode', 'role_voice_builtin', 'role_voice_description', 'role_voice_reference',
                                'role_voice_language', 'role_voice_pace', 'role_voice_instructions', 'role_voice_status']],
           show_progress='hidden')
    for component in [ui['language'], ui['bank'], ui['imported']]:
        component.change(bank_summary, [ui['language'], ui['bank'], ui['imported']], ui['bank_info'], show_progress='hidden')
    # 只撤回草案显示；这些 change 事件不发起全书或模型分析。
    def invalidate():
        return '', []
    for component in base:
        component.change(invalidate, outputs=[ui['token'], ui['plan']], show_progress='hidden')
    for component in base[:2] + base[4:]:
        component.change(lambda: ([], '书籍、解析设置或声音库已改变，请重新查看统计／生成方案。'),
                         outputs=[ui['stats'], ui['status']], show_progress='hidden')
    c['provider_state'].change(lambda provider: gr.update(visible=provider == 'Mimo'), c['provider_state'], ui['group'], show_progress='hidden')
