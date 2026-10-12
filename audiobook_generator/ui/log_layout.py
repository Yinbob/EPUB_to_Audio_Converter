"""日志标签页显示后重新适配 xterm 的行列尺寸。"""

LOG_LAYOUT_HEAD_HTML = """
<script>
(function () {
  var terminalBox = null;
  var resizeObserver = null;
  var pendingFrame = false;
  var lastWidth = 0;
  var lastHeight = 0;

  function fitVisibleLog() {
    if (pendingFrame || !terminalBox) return;
    pendingFrame = true;
    window.requestAnimationFrame(function () {
      pendingFrame = false;
      if (!terminalBox || !terminalBox.isConnected) return;
      var width = terminalBox.clientWidth;
      var height = terminalBox.clientHeight;
      // 隐藏标签页没有可测量的尺寸；再次显示时必须重新适配。
      if (width <= 0 || height <= 0) {
        lastWidth = 0;
        lastHeight = 0;
        return;
      }
      if (width === lastWidth && height === lastHeight) return;
      lastWidth = width;
      lastHeight = height;
      // gradio_log 只在挂载及 window.resize 时调用 FitAddon.fit()。
      // 复用组件自己的适配入口，不能用 CSS 拉伸文字画布（会模糊且不改变行列数）。
      window.dispatchEvent(new Event('resize'));
    });
  }

  function bindLogLayout() {
    var terminal = document.querySelector('#run_log .xterm');
    var box = terminal ? terminal.parentElement : null;
    if (box === terminalBox) return;
    if (resizeObserver) resizeObserver.disconnect();
    terminalBox = box;
    lastWidth = 0;
    lastHeight = 0;
    if (!box) return;
    resizeObserver = new ResizeObserver(fitVisibleLog);
    resizeObserver.observe(box);
    fitVisibleLog();
  }

  function boot() {
    bindLogLayout();
    // Gradio 渐进挂载组件；也兼容终端节点被重新创建。
    new MutationObserver(bindLogLayout).observe(document.body, {
      childList: true, subtree: true
    });
    if (document.fonts) {
      document.fonts.ready.then(function () {
        lastWidth = 0;
        lastHeight = 0;
        fitVisibleLog();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
</script>
"""
