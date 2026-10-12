"""不用 TTS 依赖验证日志终端的显示与重建生命周期。"""

import shutil
import subprocess
import unittest

from audiobook_generator.ui.log_layout import LOG_LAYOUT_HEAD_HTML


@unittest.skipUnless(shutil.which("node"), "需要 Node.js 执行页面脚本")
class TestLogLayout(unittest.TestCase):
    def test_hidden_visible_resize_and_remount(self):
        script = LOG_LAYOUT_HEAD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        harness = """
const assert = require('node:assert/strict');
let frames = [], resizeCount = 0, resizeCallback, mutationCallback;
let box = {clientWidth: 0, clientHeight: 0, isConnected: true};
let terminal = null;
let disconnectCount = 0;
global.window = {
  requestAnimationFrame: callback => frames.push(callback),
  dispatchEvent: event => {
    assert.equal(event.type, 'resize');
    resizeCount++;
    // 模拟 FitAddon 的 DOM 更新，不能再次触发无限适配。
    mutationCallback();
    resizeCallback();
  }
};
global.document = {
  readyState: 'complete', body: {},
  querySelector: selector => {
    assert.equal(selector, '#run_log .xterm');
    return terminal;
  }
};
global.ResizeObserver = class {
  constructor(callback) { resizeCallback = callback; }
  observe(target) { assert.equal(target, box); }
  disconnect() { disconnectCount++; }
};
global.MutationObserver = class {
  constructor(callback) { mutationCallback = callback; }
  observe() {}
};
function flush() {
  let count = 0;
  while (frames.length) {
    assert.ok(count++ < 10, '适配出现反馈循环');
    frames.shift()();
  }
}
"""
        scenarios = """
// 渐进挂载：组件出现时标签页仍隐藏。
terminal = {parentElement: box};
mutationCallback(); flush();
assert.equal(resizeCount, 0);
// 首次显示：必须从默认的行列数重新适配。
box.clientWidth = 1055; box.clientHeight = 382;
resizeCallback(); resizeCallback(); flush();
assert.equal(resizeCount, 1);
// 同尺寸的重绘不能不断广播 resize。
resizeCallback(); flush();
assert.equal(resizeCount, 1);
// 只改变高度（包括浏览器缩放导致的布局变化）也必须适配。
box.clientHeight = 600;
resizeCallback(); flush();
assert.equal(resizeCount, 2);
// 隐藏再显示，尺寸不变也需要重新适配。
box.clientWidth = 0; box.clientHeight = 0;
resizeCallback(); flush();
box.clientWidth = 1055; box.clientHeight = 600;
resizeCallback(); flush();
assert.equal(resizeCount, 3);
// 节点重建时解绑旧节点，再适配新终端。
box.isConnected = false;
box = {clientWidth: 700, clientHeight: 400, isConnected: true};
terminal = {parentElement: box};
mutationCallback(); flush();
assert.equal(disconnectCount, 1);
assert.equal(resizeCount, 4);
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", harness + script + scenarios],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
