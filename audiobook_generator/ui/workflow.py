"""生成流程导航、模块排版与轻量交互。"""


def workflow_steps_html():
    return '''<nav class="workflow-steps" aria-label="生成步骤">
      <a href="#book_setup" data-step="book"><span>1</span><b>准备书籍</b><small>上传与章节范围</small></a>
      <a href="#voice_setup" data-step="voice"><span>2</span><b>选择声音</b><small>引擎与音色</small></a>
      <a href="#role_studio" data-step="role"><span>3</span><b>多角色配音</b><small>可选 · 剧本与试听</small></a>
      <a href="#generation_setup" data-step="generate"><span>4</span><b>确认生成</b><small>生成后前往资源库</small></a>
    </nav><p id="workflow_next" class="workflow-next" role="status">从第 1 步开始：上传一本书，或添加多本书批量生成。</p><div id="workflow_result" class="workflow-result" hidden><span id="workflow_result_text"></span><button type="button" id="workflow_library_link" class="btn-ghost">前往资源库试听与下载 →</button></div>'''

WORKFLOW_HEAD_HTML = '''<script>
(function () {
  var resultParseOnly = false;
  function sync() {
    var state = document.querySelector('#generation_summary [data-files]');
    if (!state) return;
    var count = Number(state.dataset.files || 0);
    var ready = state.dataset.ready === '1';
    var hint = document.getElementById('workflow_next');
    var message = count ? (state.textContent || '') : '从第 1 步开始：上传一本书，或添加多本书批量生成。';
    if (hint && hint.textContent !== message) hint.textContent = message;
    document.querySelectorAll('.workflow-steps a').forEach(function (link) {
      var step = link.dataset.step;
      var current = count ? (ready ? 'generate' : 'role') : 'book';
      var value = step === current ? 'step' : null;
      if (value && link.getAttribute('aria-current') !== value) link.setAttribute('aria-current', value);
      if (!value && link.hasAttribute('aria-current')) link.removeAttribute('aria-current');
    });
    var box = document.getElementById('progress_container');
    var start = document.querySelector('#generation_start');
    var mode = box ? box.dataset.mode : 'idle';
    var busy = ['starting', 'running', 'book_done'].indexOf(mode) >= 0;
    if (start && start.getAttribute('aria-busy') !== String(!!busy)) start.setAttribute('aria-busy', String(!!busy));
    var startButton = start && (start.tagName === 'BUTTON' ? start : start.querySelector('button'));
    if (startButton) startButton.disabled = busy || !ready;
    var stop = document.querySelector('#generation_stop');
    var stopButton = stop && (stop.tagName === 'BUTTON' ? stop : stop.querySelector('button'));
    var active = busy;
    if (stopButton) stopButton.disabled = !active;
    var result = document.getElementById('workflow_result');
    var text = document.getElementById('workflow_result_text');
    if (result && box && ['finished', 'interrupted', 'failed'].indexOf(mode) >= 0) {
      result.hidden = false;
      // 完成提示读取本次结果，避免修改下一次设置时改写上次的完成状态。
      var parseOnly = box.textContent.indexOf('预解析') >= 0;
      resultParseOnly = parseOnly;
      var resultText = parseOnly && mode === 'finished' ? '章节解析已完成。下一步：到日志查看章节和字数；本次没有生成音频。' : mode === 'finished' ? '本次生成已完成。下一步：到资源库选择章节，试听并下载。' : '本次生成已停止或出现错误。可到资源库保存已有结果，或查看运行日志。';
      if (text && text.textContent !== resultText) text.textContent = resultText;
      var link = document.getElementById('workflow_library_link');
      var linkText = parseOnly ? '查看解析日志 →' : '前往资源库试听与下载 →';
      if (link && link.textContent !== linkText) link.textContent = linkText;
    } else if (result && active) result.hidden = true;
  }
  function stateIsParseOnly() {
    return resultParseOnly;
  }
  function boot() {
    sync();
    new MutationObserver(sync).observe(document.body, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['class','data-files','data-ready','data-mode']});
    document.addEventListener('click', function (event) {
      if (event.target.closest('#workflow_library_link')) {
        // 按 Gradio 标签的固定标识定位，不依赖版本间会变化的包装层类名。
        var tabId = stateIsParseOnly() ? 'tab_logs' : 'tab_library';
        var tab = document.querySelector('#studio_tabs [role="tablist"] button[role="tab"][data-tab-id="' + tabId + '"]');
        if (tab && !tab.disabled) {
          event.preventDefault();
          tab.click();
          window.scrollTo({top: 0, behavior: 'smooth'});
        }
        return;
      }
      var step = event.target.closest('.workflow-steps a');
      if (!step) return;
      var target = document.querySelector(step.getAttribute('href'));
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'});
      var title = target.querySelector('h3, .card-title');
      if (title) {title.setAttribute('tabindex','-1'); title.focus({preventScroll:true});}
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
</script>'''

WORKFLOW_CSS = '''
:root { --ease-out: cubic-bezier(0.23, 1, 0.32, 1); }
/* 页面宽度沿用 63aa489，首页标题单独调整，不影响其他页面。 */
.hero.home-hero { padding: clamp(24px, 4vw, 40px) 8px 32px; }
.hero.home-hero h1 {
  font-size: clamp(2rem, 5.5vw, 3rem) !important; font-weight: 700 !important;
  line-height: 1.2; margin-bottom: 16px !important;
}
.hero.home-hero p { font-size: clamp(1.1rem, 1.6vw, 1.2rem); line-height: 1.75; max-width: 640px; }
.workflow-result[hidden] { display: none !important; }
.workflow-result { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px; border-radius: 12px; background-color: var(--apple-blue-soft); color: var(--apple-text); font-size: .9rem; }
.workflow-result button { flex-shrink: 0; padding: 10px 16px; }
.workflow-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.workflow-steps a { display: grid; grid-template-columns: 28px 1fr; column-gap: 10px; padding: 12px; border-radius: 12px; color: var(--apple-text-2); text-decoration: none; background-color: var(--ata-glass-soft); }
.workflow-steps a span { grid-row: span 2; align-self: center; display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid var(--apple-border); border-radius: 50%; font-size: .8rem; }
.workflow-steps b { font-size: .9rem; font-weight: 600; }
.workflow-steps small { color: var(--apple-text-3); font-size: .75rem; margin-top: 4px; }
.workflow-steps a[aria-current=step] { background-color: var(--apple-blue-soft); color: var(--apple-blue); }
.workflow-next { margin: 4px 0 12px; color: var(--apple-text-2); font-size: .86rem; line-height: 1.6; }
#book_setup, #voice_setup, #role_studio, #generation_setup { scroll-margin-top: 24px; }
/* 桌面上传区左右各拓宽 8px，仍留在卡片内；窄屏沿用原宽。 */
/* Group 的外层 styler 也默认裁切，须与表单一起放行，避免截断左右虚线。 */
#book_setup > .styler:has(.book-file-upload),
#book_setup .form:has(> .book-file-upload) {
  overflow: visible !important;
  background-color: transparent !important;
}
#book_setup .book-file-upload:not(:has(.file-preview)) { overflow: visible !important; }
@media (min-width: 720px) {
  #book_setup .book-file-upload {
    width: calc(100% + 16px) !important; max-width: none !important;
    margin-inline: -8px !important;
  }
}
.optional-label { margin-left: 8px; color: var(--apple-text-3); font-size: .8rem; font-weight: 400; }
#role_studio .advanced-section-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
#role_studio .advanced-section-copy h3 { margin: 0; font-size: 1.1rem; }
#role_studio .advanced-section-copy p { color: var(--apple-text-2); font-size: .86rem; margin: 5px 0 0; }
#role_studio .advanced-subsection-head { margin: 24px 0 12px; display: flex; gap: 12px; align-items: flex-start; }
#role_studio .advanced-subsection-head h4 { margin: 0; font-size: 1rem; }
#role_studio .advanced-subsection-head p { margin: 5px 0 0; color: var(--apple-text-2); font-size: .86rem; line-height: 1.6; }
#role_studio .role-step-number { display: grid; place-items: center; min-width: 26px; height: 26px; border-radius: 50%; background-color: var(--apple-blue-soft); color: var(--apple-blue); font-size: .8rem; }
#role_studio .advanced-field-row { display: grid !important; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; }
#role_studio .advanced-action-row { gap: 12px; }
#role_studio .role-workflow-hint { padding: 12px 16px; border-radius: 12px; background-color: var(--apple-blue-soft); color: var(--apple-text); font-size: .86rem; }
#role_studio .role-details { margin: 8px 0 !important; }
/* Gradio 自动合并的表单默认只有 1px 间隔，玻璃选项需保留独立边界。 */
.app-card .form, #advanced_modal .form { gap: 12px !important; }
.app-card .form:has(> .toggle), #advanced_modal .form:has(> .toggle) {
  margin-block: 12px !important;
  overflow: visible !important;
}
#role_studio .advanced-field-row > .form:only-child,
#advanced_modal .advanced-field-row > .form:only-child { grid-column: 1 / -1; }
/* 网格放在真正包含选项的表单上，避免 Gradio 的包装层只占半列。 */
.app-card .toggle-grid, #advanced_modal .toggle-grid { display: block !important; }
.app-card .toggle-grid .form, #advanced_modal .toggle-grid .form {
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
#role_studio .toggle-grid .form { grid-template-columns: minmax(0, 1fr); }
@media (max-width: 559px) {
  .app-card .toggle-grid .form, #advanced_modal .toggle-grid .form { grid-template-columns: minmax(0, 1fr); }
}
#generation_setup > .styler { gap: 16px !important; }
#generation_setup .row-cta { gap: 20px !important; }
#role_confirmation_probe_host { position: absolute !important; width: 1px !important; height: 1px !important; overflow: hidden !important; clip-path: inset(50%); }
.generation-summary { font-size: .95rem; line-height: 1.7; color: var(--apple-text-2); }
#result_library_btn { margin-top: 8px; }
/* 阴影只属于按钮本身，组件外壳不再有矩形投影或裁切。 */
.gradio-container button.btn-primary, .gradio-container a.btn-primary, .gradio-container .btn-primary button {
  border: 0 !important; box-shadow: 0 2px 4px rgba(0,0,0,.08), 0 6px 14px rgba(0,113,227,.16) !important;
  border-radius: 12px !important; animation: none !important;
  transition: transform 160ms var(--ease-out), opacity 160ms ease !important;
}
.gradio-container .btn-primary:not(button):not(a) { box-shadow: none !important; background-color: transparent !important; border: 0 !important; overflow: visible !important; }
.gradio-container button.btn-primary:active:not(:disabled), .gradio-container a.btn-primary:active { transform: scale(.98) !important; }
.gradio-container button.btn-primary:disabled { opacity: .5; box-shadow: none !important; cursor: not-allowed !important; transform: none !important; }
.gradio-container .btn-primary:hover, .gradio-container .btn-ghost:hover, .gradio-container .btn-mini:hover, .gradio-container .btn-danger:hover { transform: none !important; }
.gradio-container .btn-ghost, .gradio-container .btn-mini, .gradio-container .btn-danger { border-radius: 12px !important; }
.gradio-container button:focus-visible, .workflow-steps a:focus-visible { outline: 3px solid var(--apple-blue) !important; outline-offset: 3px; }
#library_workspace .library-toolbar { align-items: end; gap: 16px; margin-bottom: 24px; }
#library_workspace .library-toolbar > button { margin-bottom: 2px; }
#library_workspace .library-columns { gap: 28px; align-items: stretch; }
#library_files, #library_export { min-width: 0 !important; }
#library_export { border-left: 1px solid var(--apple-border-soft); padding-left: 28px; }
.library-heading { margin: 0; font-size: 1.05rem; }
.library-selection h3 { font-size: 1.05rem; overflow-wrap: anywhere; margin: 0 0 8px; }
.library-selection p { color: var(--apple-text-2); font-size: .86rem; margin: 0; }
#library_file_list { border: 0 !important; background-color: transparent !important; padding: 0 !important; }
#library_file_list .wrap { display: flex !important; flex-direction: column !important; gap: 8px !important; }
#library_file_list label {
  box-sizing: border-box; width: 100% !important; min-height: 48px; margin: 0 !important;
  padding: 13px 16px !important; border: 1px solid var(--apple-border-soft) !important;
  border-radius: 14px !important; display: flex !important; align-items: center; gap: 12px;
  background-image: none !important; background-color: var(--ata-glass-soft) !important;
  color: var(--apple-text) !important; font-weight: 500 !important; box-shadow: none !important;
  overflow-wrap: anywhere; cursor: pointer;
  transition: background-color 160ms var(--ease-out), border-color 160ms var(--ease-out) !important;
}
/* 悬停只提示未选项可点击；勾选才是持续选中状态，焦点不改变它。 */
@media (hover: hover) and (pointer: fine) {
  #library_file_list label:not(:has(input:checked)):hover { background-color: var(--ata-hover) !important; border-color: var(--apple-border) !important; }
}
#library_file_list label:has(input:checked),
#library_file_list label:has(input:checked):hover,
#library_file_list label:has(input:checked):active,
#library_file_list label:has(input:checked):focus-within {
  background-image: none !important; background-color: var(--apple-blue-soft) !important;
  color: var(--apple-text) !important; border-color: var(--apple-blue) !important; box-shadow: none !important;
}
#library_file_list label:has(input:checked) span { color: var(--apple-text) !important; }
#library_file_list label:has(input:focus-visible) { outline: 2px solid var(--apple-blue); outline-offset: -4px; }
#library_file_list label span { min-width: 0; white-space: normal; overflow-wrap: anywhere; }
#library_file_list input { flex: 0 0 auto; accent-color: var(--apple-blue); }
/* 点击焦点不借用文本框光圈，键盘焦点由上方整行内描边提示。 */
#library_file_list input[type="checkbox"],
#library_file_list input[type="checkbox"]:focus {
  box-shadow: none !important; outline: none !important;
}
#library_file_list input[type="checkbox"]:checked { background-color: var(--apple-blue) !important; border-color: var(--apple-blue) !important; }
#library_file_list { max-height: 520px; overflow-y: auto !important; }
#library_direct_download { min-height: 80px; }
#library_direct_download .file { min-width: 0; }
#library_zip_panel { padding: 8px 0 16px !important; gap: 16px; }
#library_cleanup { margin-top: 24px; border-top: 1px solid var(--apple-border-soft) !important; padding-top: 12px; }
.lib-ready { min-height: auto !important; padding: 16px !important; }
.lib-empty { min-height: 100px !important; padding: 16px !important; }
.lib-empty-icon { display: none; }
.lib-ready h3 { font-size: 1rem; }
#role_config_panel { opacity: 1; transition: opacity 200ms var(--ease-out); }
@starting-style { #role_config_panel { opacity: 0; } }
@media (hover: hover) and (pointer: fine) {
  .workflow-steps a:hover { background-color: var(--ata-hover); }
  .gradio-container button.btn-primary:hover:not(:disabled) { transform: translateY(-1px) !important; }
}
@media (max-width: 720px) {
  .workflow-result { flex-direction: column; align-items: stretch; }
  .workflow-steps { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .workflow-steps a { padding: 10px; }
  #library_workspace .library-columns { flex-direction: column; }
  #library_export { border-left: 0; border-top: 1px solid var(--apple-border-soft); padding: 20px 0 0; }
  #role_studio .advanced-field-row { grid-template-columns: 1fr; }
  #library_workspace .library-toolbar { flex-wrap: wrap; }
  #library_workspace .library-toolbar > button { width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .gradio-container button.btn-primary:active:not(:disabled), .gradio-container button.btn-primary:hover:not(:disabled), .gradio-container a.btn-primary:active { transform: none !important; }
  #role_config_panel { transition-duration: 0ms; }
}
'''
