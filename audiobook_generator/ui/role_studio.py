"""多角色工作区的局部样式与等待结果文案，继承全站主题。"""
import html
import json
import queue
import threading
import time
from audiobook_generator.role_script.split_control import SplitAborted, split_control_scope

SPLIT_ACTIVITY_CSS = """
#role_split_status .role-split-activity { position: relative; display: grid; grid-template-columns: 64px minmax(0, 1fr) minmax(224px, .65fr); align-items: center; gap: 16px 20px; padding: 22px; border: 1px solid var(--apple-border); border-radius: 18px; background-color: var(--ata-glass-soft); }
#role_split_status .role-split-copy { min-width: 0; }
#role_split_status [data-state="starting"], #role_split_status [data-state="running"] { border-color: var(--apple-blue); background-color: var(--apple-blue-soft); box-shadow: var(--apple-shadow-blue); }
#role_split_status .role-split-heading { color: var(--apple-text); font-size: 1.08rem; font-weight: 650; line-height: 1.5; }
#role_split_status .role-split-wave { display: flex; align-items: center; justify-content: center; gap: 3px; height: 64px; color: var(--apple-blue); }
#role_split_status .role-split-wave i { display: block; width: 3px; height: var(--bar-height); flex: 0 0 3px; border-radius: 4px; background-color: currentColor; transform: scaleY(.35); opacity: .45; }
#role_split_status [data-state="starting"] .role-split-wave i, #role_split_status [data-state="running"] .role-split-wave i { animation: role-split-wave 1400ms cubic-bezier(0.77, 0, 0.175, 1) infinite; animation-delay: calc(var(--bar-index) * -80ms); }
#role_split_status .role-split-detail { margin-top: 10px; color: var(--apple-text-2); white-space: pre-line; overflow-wrap: anywhere; line-height: 1.65; }
#role_split_status .role-split-elapsed { display: block; margin-top: 10px; color: var(--apple-text); font-size: .86rem; font-variant-numeric: tabular-nums; }
#role_split_status .role-split-stages { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 20px; padding-left: 24px; border-left: 1px solid var(--apple-border-soft); color: var(--apple-text-2); font-size: .8rem; line-height: 1.6; }
#role_split_status .role-split-stages [aria-current="step"] { color: var(--apple-blue); font-weight: 650; }
#role_split_status .role-split-track { grid-column: 1 / -1; position: relative; height: 3px; overflow: hidden; border-radius: 4px; background-color: var(--apple-border-soft); }
#role_split_status .role-split-track span { display: block; width: 30%; height: 100%; border-radius: inherit; background-color: var(--apple-blue); transform: translateX(-110%); }
#role_split_status [data-state="starting"] .role-split-track span, #role_split_status [data-state="running"] .role-split-track span { animation: role-split-flow 2200ms linear infinite; }
#role_split_status [data-state="failed"] .role-split-heading { color: var(--apple-red); }
#role_split_status [data-state="done"] .role-split-heading { color: var(--apple-green); }
#role_split_status [data-state="failed"] .role-split-wave { color: var(--apple-red); }
#role_split_status [data-state="done"] .role-split-wave { color: var(--apple-green); }
@keyframes role-split-wave { 0%, 100% { transform: scaleY(.35); opacity: .45; } 50% { transform: scaleY(1); opacity: 1; } }
@keyframes role-split-flow { to { transform: translateX(440%); } }
@media (max-width: 1000px) {
  #role_split_status .role-split-activity { grid-template-columns: 64px minmax(0, 1fr); }
  #role_split_status .role-split-stages { grid-column: 1 / -1; padding: 14px 0 0; border-left: 0; border-top: 1px solid var(--apple-border-soft); }
}
@media (max-width: 480px) {
  #role_split_status .role-split-activity { grid-template-columns: 48px minmax(0, 1fr); gap: 14px; padding: 18px; }
  #role_split_status .role-split-wave { gap: 2px; }
  #role_split_status .role-split-wave i { width: 2px; flex-basis: 2px; }
}
"""


ROLE_STUDIO_CSS = """
#role_studio { --role-field-radius: 18px; }
#role_studio .role-section-title h4 { margin: 0 0 6px; font-size: 1.08rem; font-weight: 650; color: var(--apple-text); }
#role_studio .role-section-title p { margin: 0; color: var(--apple-text-2); line-height: 1.65; font-size: .88rem; }
#role_studio .role-section-title { padding: 20px 0 12px; }
#role_studio .role-workflow-hint { color: var(--apple-text-2); margin: 8px 0 16px; line-height: 1.65; }
#role_studio .role-attribution-layout { gap: 28px; align-items: flex-start; }
#role_studio .role-tool-nav { min-width: 0; }
#role_studio .role-tool-nav .wrap { flex-direction: column; gap: 10px; }
#role_studio .role-tool-nav label { min-height: 48px; padding: 12px; border-radius: 12px; }
#role_studio .role-attribution-work { min-width: 0; border-left: 1px solid var(--apple-border-soft); padding-left: 28px; }
#role_studio .role-task-panel { gap: 16px; }
#role_studio .role-task-panel .role-section-title { padding-top: 0; }
#role_studio .role-review-notice { border: 1px solid var(--apple-border); border-radius: 14px; padding: 16px 18px; background-color: var(--ata-glass-soft); color: var(--apple-text); line-height: 1.65; overflow-wrap: anywhere; }
#role_studio .role-review-notice strong { display: block; margin-bottom: 4px; }
#role_studio .role-review-notice[data-state="success"] { border-color: var(--apple-green); }
#role_studio .role-review-notice[data-state="error"] { border-color: var(--apple-red); }
#role_studio .role-merge-preview { padding: 16px; border-radius: 14px; border: 1px solid var(--apple-border); color: var(--apple-text); background-color: var(--ata-glass-soft); line-height: 1.7; overflow-wrap: anywhere; }
#role_studio .role-merge-preview p { margin: 6px 0 0; }
#role_studio .role-next-step { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--apple-border-soft); }
#role_studio .role-setup-tabs, #role_studio .role-workspace-tabs { border: 0; background-color: transparent; }
#role_studio .tab-nav { gap: 4px; padding: 4px; border: 0; border-radius: 16px; background-color: var(--ata-glass-soft); }
#role_studio .tab-nav button { min-height: 44px; flex: 1 1 auto; border-radius: 12px; white-space: normal; line-height: 1.4; }
#role_studio .tabitem { padding: 12px 0 0; border: 0; background-color: transparent; }
#role_studio .role-field { border-radius: var(--role-field-radius) !important; min-width: 0; }
#role_studio .role-field > .wrap, #role_studio .role-field > .form { border-radius: var(--role-field-radius) !important; }
#role_studio textarea, #role_studio input[type="text"], #role_studio input[type="password"], #role_studio input[type="number"] {
  border-radius: 12px !important; color: var(--apple-text); caret-color: var(--apple-blue);
}
#role_studio textarea { line-height: 1.65; }
#role_studio ::placeholder { color: var(--apple-text-2); opacity: 1; }
#role_studio .role-field:focus-within { outline: 2px solid var(--apple-blue); outline-offset: 2px; }
/* 展开菜单层级由全站共用规则处理，角色区只设置外观。 */
#role_studio ul.options { border-radius: 14px; }
#role_studio .role-segment-context { margin-top: 20px; border-top: 1px solid var(--apple-border-soft); padding-top: 12px; }
#role_studio .role-segment-context summary { cursor: pointer; padding: 10px 0; color: var(--apple-blue); font-weight: 600; }
#role_studio .role-segment-context summary:focus-visible { outline: 2px solid var(--apple-blue); outline-offset: 3px; border-radius: 8px; }
#role_studio .role-segment-context p { color: var(--apple-text-2); line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
#role_studio .role-segment-context strong { color: var(--apple-text); margin-inline: 6px; }
#role_studio .role-voice-columns { gap: 28px; align-items: flex-start; }
#role_studio .role-voice-columns > .column { min-width: 0; }
#role_studio .role-listen-pane { border-left: 1px solid var(--apple-border-soft); padding-left: 28px; }
#role_studio .role-action-row { gap: 10px; align-items: stretch; }
#role_studio .role-action-row button { min-height: 44px; white-space: normal; }
#role_studio #role_split_btn, #role_studio #role_split_stop_btn { min-height: 48px; margin-top: 8px; }
#role_studio #role_split_note { margin-top: 16px !important; }
#role_studio #role_split_status { min-height: 0; margin-top: 16px !important; padding: 0; border-radius: 18px; background-color: transparent; }
#role_studio #role_split_status p { margin: 0; line-height: 1.65; color: var(--apple-text-2); }
#role_studio #role_split_status .generating { border-radius: 18px; }
@keyframes role-split-spin { to { transform: rotate(360deg); } }
#role_studio #role_preview_btn { min-height: 48px; margin-top: 8px; }
#role_studio #role_preview_audio { margin-top: 24px !important; margin-bottom: 12px; }
#role_studio .role-caption { color: var(--apple-text-2); font-size: .84rem; line-height: 1.65; }
#role_studio .role-summary { max-height: 360px; overflow-y: auto; overflow-wrap: anywhere; line-height: 1.7; }
#role_studio .role-summary table { width: 100%; table-layout: fixed; font-size: .88rem; }
#role_studio .role-summary th, #role_studio .role-summary td { white-space: normal; overflow-wrap: anywhere; padding: 10px 12px; }
#role_studio .role-summary th:first-child, #role_studio .role-summary td:first-child { width: 60%; }
#role_studio #role_parameter_table { max-width: 100%; min-width: 0; border-radius: 18px; }
#role_studio #role_parameter_table .table-wrap { overflow-x: auto; }
#role_studio .role-diagnostics { max-height: 240px; overflow: auto; overflow-wrap: anywhere; font-size: .84rem; }
#role_studio .role-confirm-bar { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--apple-border-soft); gap: 16px; align-items: center; }
#role_studio .role-confirm-bar button { min-height: 48px; }
#role_studio .role-confirm-bar p { color: var(--apple-text-2); line-height: 1.6; margin: 0; }
#role_studio #role_editor { animation: role-workspace-reveal 260ms cubic-bezier(0.23, 1, 0.32, 1); }
#role_studio button { transition: background-color 160ms ease, opacity 160ms ease; }
#role_studio button:focus-visible { outline: 2px solid var(--apple-blue) !important; outline-offset: 3px; }
#role_studio button:disabled { cursor: not-allowed; opacity: .5; }
#role_studio #role_split_btn, #role_studio #role_preview_btn, #role_studio #role_confirm_btn { transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), background-color 160ms ease, opacity 160ms ease !important; }
#role_studio #role_split_btn:active:not(:disabled), #role_studio #role_preview_btn:active:not(:disabled), #role_studio #role_confirm_btn:active:not(:disabled) { transform: scale(.97); }
#role_studio #role_confirm_btn { position: relative; overflow: hidden; padding-right: 44px !important; }
#role_studio #role_confirm_btn[data-role-confirm-state="pending"], #role_studio #role_confirm_btn[data-role-confirm-state="confirmed"] { font-size: 0 !important; }
#role_studio #role_confirm_btn[data-role-confirm-state="pending"]::before { content: "正在核对角色参数…"; font-size: .9rem; }
#role_studio #role_confirm_btn[data-role-confirm-state="confirmed"] { background-image: none !important; background-color: var(--apple-green) !important; border-color: var(--apple-green) !important; color: var(--apple-surface) !important; }
#role_studio #role_confirm_btn[data-role-confirm-state="confirmed"]::before { content: "已确认，可以开始生成"; font-size: .9rem; }
#role_studio #role_confirm_btn::after { content: ""; position: absolute; right: 20px; top: calc(50% - 7px); width: 8px; height: 14px; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; opacity: 0; transform: rotate(45deg) scale(.65); transition: transform 240ms cubic-bezier(0.23, 1, 0.32, 1), opacity 160ms ease; }
#role_studio #role_confirm_btn[data-role-confirm-state="confirmed"]::after { opacity: 1; transform: rotate(45deg) scale(1); }
#role_studio #role_confirm_btn[data-role-confirm-state="pending"]::after { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; opacity: .85; animation: role-split-spin 1s linear infinite; }
@media (hover: hover) and (pointer: fine) {
  #role_studio #role_split_btn:hover:not(:disabled), #role_studio #role_preview_btn:hover:not(:disabled), #role_studio #role_confirm_btn:hover:not(:disabled) { transform: translateY(-1px); }
  #role_studio #role_split_btn:active:not(:disabled), #role_studio #role_preview_btn:active:not(:disabled), #role_studio #role_confirm_btn:active:not(:disabled) { transform: scale(.97); }
}
@keyframes role-workspace-reveal { from { opacity: .35; } to { opacity: 1; } }
@media (max-width: 760px) {
  #role_studio .role-attribution-layout { flex-direction: column; gap: 20px; }
  #role_studio .role-attribution-layout > .column { width: 100%; flex-basis: auto !important; }
  #role_studio .role-attribution-work { border-left: 0; border-top: 1px solid var(--apple-border-soft); padding: 20px 0 0; }
  #role_studio .role-voice-columns { flex-direction: column; gap: 12px; }
  #role_studio .role-voice-columns > .column { width: 100%; flex-basis: auto !important; }
  #role_studio .role-listen-pane { border-left: 0; border-top: 1px solid var(--apple-border-soft); padding: 16px 0 0; }
  #role_studio .role-confirm-bar { flex-direction: column; align-items: stretch; }
  #role_studio .tab-nav button { font-size: .86rem; padding: 10px 8px; }
}
@media (max-width: 480px) {
  #role_studio #role_preview_audio { margin-top: 20px !important; }
}
""" + SPLIT_ACTIVITY_CSS


def review_notice(message, state='idle'):
    titles = {'idle': '当前操作', 'pending': '正在保存修改…',
              'success': '修改已保存', 'error': '未能保存修改'}
    if state not in titles:
        state = 'idle'
    return (f'<div class="role-review-notice" data-state="{state}" role="status" aria-live="polite">'
            f'<strong>{titles[state]}</strong><span>{html.escape(str(message))}</span></div>')


def split_result_status(generated, validation):
    if generated:
        return '剧本已准备好。请在下方选择角色，调整声音并试听，再确认用于生成。'
    if '失败' in str(validation or ''):
        lines = [line.strip().replace('**', '') for line in str(validation).splitlines() if line.strip()]
        detail = ' '.join(lines[1:-1] or lines)[:320]
        return ('**剧本未生成成功**\n\n' + html.escape(detail) +
                '\n\n请检查「DeepSeek 连接」和所选章节，修正后可重新生成；也可在「导入与选项」上传已有剧本。')
    return '等待生成剧本。分析时会显示人物索引、章节拆分等当前阶段；长章节可能需要几分钟，请保持页面打开。'


def render_split_status(state='idle', detail='', started=None):
    """独立于 Gradio 原生遮罩的真实阶段提示，不显示虚构百分比。"""
    titles = {'idle': '等待生成剧本', 'starting': '正在准备剧本', 'running': 'DeepSeek 正在生成剧本',
              'done': '剧本已准备好', 'failed': '剧本未生成成功',
              'stopping': '正在停止拆分', 'cancelled': '已停止拆分'}
    if state not in titles:
        state = 'idle'
    busy = state in ('starting', 'running')
    detail = detail or '分析时会显示当前阶段；长章节可能需要几分钟。'
    stamp = int(started or time.time() * 1000) if busy else 0
    seconds = max(0, int((time.time() * 1000 - stamp) / 1000)) if busy else 0
    elapsed = f'{seconds} 秒' if seconds < 60 else f'{seconds // 60} 分 {seconds % 60} 秒'
    clock = f'<span class="role-split-elapsed" aria-live="off">已等待 {elapsed}</span>' if busy else ''
    heights = (16, 24, 36, 48, 36, 24, 16, 24, 36, 48, 36)
    wave = '<div class="role-split-wave" aria-hidden="true">' + ''.join(
        f'<i style="--bar-index:{i};--bar-height:{height}px"></i>' for i, height in enumerate(heights)) + '</div>'
    # 只突出实际回调对应的阶段，不按等待时间推算，也不把前面的阶段标成已完成。
    phase = None
    if state == 'done' or (busy and any(word in detail for word in ('已保存', '保存结果'))):
        phase = 3
    elif busy and any(word in detail for word in ('人物表', '人物索引', '叙述者', '叙述视角')):
        phase = 1
    elif busy and any(word in detail for word in ('正在拆分', '逐段')):
        phase = 2
    elif busy and '读取' in detail:
        phase = 0
    stages = '<div class="role-split-stages" aria-label="处理阶段">' + ''.join(
        f'<span' + (' aria-current="step"' if i == phase else '') + f'>{label}</span>'
        for i, label in enumerate(('读取章节', '梳理人物', '拆分剧本', '保存结果'))) + '</div>'
    track = '<div class="role-split-track" aria-hidden="true"><span></span></div>' if busy else ''
    live = 'assertive' if state == 'failed' else 'polite'
    return (f'<div class="role-split-activity" data-state="{state}" data-role-split-started="{stamp}">'
            f'{wave}<div class="role-split-copy"><div role="status" aria-live="{live}" aria-atomic="true">'
            f'<div class="role-split-heading">{titles[state]}</div>'
            f'<div class="role-split-detail">{html.escape(str(detail).replace("**", ""))}</div></div>{clock}</div>'
            f'{stages}{track}</div>')


# 点击反馈先在本地出现；计时只更新文字，不重挂载等待动画。
ROLE_SPLIT_HEAD = '<script>' + r'''
(() => {
  const pending = PENDING_TEMPLATE;
  let watchedStudio = null;
  let roleObserver = null;
  function syncConfirmation() {
    const button = document.querySelector('#role_confirm_btn');
    if (!button) return;
    const confirmed = document.querySelector('#role_confirmation_probe')?.dataset.confirmed === '1';
    const state = button.disabled ? 'pending' : (confirmed ? 'confirmed' : 'idle');
    if (button.dataset.roleConfirmState !== state) button.dataset.roleConfirmState = state;
    button.setAttribute('aria-busy', String(state === 'pending'));
    button.setAttribute('aria-label', state === 'pending' ? '正在核对角色参数' :
      state === 'confirmed' ? '已确认，可以开始生成。再次点击可重新确认剧本与角色参数' : '确认剧本与角色参数');
  }
  function watchConfirmation() {
    const studio = document.querySelector('#role_studio');
    if (!studio || studio === watchedStudio) return;
    roleObserver?.disconnect();
    watchedStudio = studio;
    roleObserver = new MutationObserver(syncConfirmation);
    roleObserver.observe(studio, {childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ['disabled', 'data-confirmed']});
    syncConfirmation();
  }
  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('#role_split_btn');
    if (!button || button.disabled) return;
    const host = document.querySelector('#role_split_status .role-split-activity');
    if (!host) return;
    // 只更新我们自己的原始 HTML，保留 Gradio/Svelte 的组件与锚点。
    const template = document.createElement('template');
    template.innerHTML = pending;
    host.innerHTML = template.content.firstElementChild.innerHTML;
    host.dataset.state = 'starting';
    host.dataset.roleSplitStarted = String(Date.now());
  }, true);
  setInterval(() => {
    watchConfirmation();
    const box = document.querySelector('#role_split_status [data-role-split-started]');
    const elapsed = box?.querySelector('.role-split-elapsed');
    if (!elapsed) return;
    const seconds = Math.max(0, Math.floor((Date.now() - Number(box.dataset.roleSplitStarted)) / 1000));
    elapsed.textContent = seconds < 60 ? `已等待 ${seconds} 秒` : `已等待 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  }, 1000);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watchConfirmation, {once: true});
  else watchConfirmation();
})();
'''.replace('PENDING_TEMPLATE', json.dumps(render_split_status('starting', '请求已提交，正在等待开始分析…'), ensure_ascii=False)) + '</script>'


def iter_split_events(run, values, heartbeat=1.0, on_finish=None, control=None):
    """同步拆分在独立线程执行，向 Gradio 生成器持续传递阶段与结果。"""
    events = queue.Queue()
    worker_started = False

    def report(value, desc=''):
        if control:
            control.check()
            if desc:
                control.phase = str(desc)
        if desc:
            events.put({'state': 'running', 'message': str(desc)})

    def worker():
        try:
            if control:
                control.report = lambda value, desc='': events.put({'state': 'running', 'message': str(desc)})
            with split_control_scope(control):
                if control:
                    control.check()
                event = {'state': 'result', 'result': run(*values, progress=report)}
        except SplitAborted as exc:
            event = {'state': exc.state, 'message': str(exc)}
        except Exception as exc:
            event = {'state': 'failed', 'message': str(exc)}
        finally:
            if control and 'event' in locals():
                control.result = event.get('result')
            if on_finish:
                on_finish()
            if control:
                control.finished.set()
        events.put(event)

    try:
        yield {'state': 'starting', 'message': '正在读取书籍与所选章节…'}
        threading.Thread(target=worker, name='role-script-feedback', daemon=True).start()
        worker_started = True
        while True:
            try:
                event = events.get(timeout=heartbeat)
            except queue.Empty:
                yield {'state': 'heartbeat'}
                continue
            yield event
            if event['state'] in ('result', 'failed', 'cancelled'):
                break
    finally:
        # 请求关闭不能解除仍在运行的工作线程占用；线程结束才释放。
        if not worker_started and on_finish:
            on_finish()
        if not worker_started and control:
            control.finished.set()
