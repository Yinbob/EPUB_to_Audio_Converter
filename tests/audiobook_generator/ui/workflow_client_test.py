"""完成提示的真实客户端脚本检查，不访问浏览器或调用合成服务。"""
import json
import shutil
import subprocess
import unittest

from audiobook_generator.ui.workflow import WORKFLOW_HEAD_HTML


@unittest.skipUnless(shutil.which('node'), '客户端脚本检查需要 Node')
class WorkflowClientTest(unittest.TestCase):
    def test_completion_link_selects_library_or_logs_by_stable_tab_id(self):
        source = WORKFLOW_HEAD_HTML.removeprefix('<script>').removesuffix('</script>')
        harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
let onClick, sync, prevented = 0, scrolled = 0;
const clicks = [];
const summary = {dataset: {files: '1', ready: '1'}, textContent: '已准备'};
const progress = {dataset: {mode: 'finished'}, textContent: '生成已完成'};
const elements = {
  workflow_next: {}, workflow_result: {hidden: true},
  workflow_result_text: {}, workflow_library_link: {}
};
const library = {disabled: false, click: () => clicks.push('library')};
const logs = {disabled: false, click: () => clicks.push('logs')};
const selectors = {
  '#generation_summary [data-files]': summary,
  '#studio_tabs [role="tablist"] button[role="tab"][data-tab-id="tab_library"]': library,
  '#studio_tabs [role="tablist"] button[role="tab"][data-tab-id="tab_logs"]': logs
};
const document = {
  readyState: 'complete', body: {},
  getElementById: id => id === 'progress_container' ? progress : elements[id],
  querySelector: selector => selectors[selector] || null,
  querySelectorAll: selector => {
    assert.equal(selector, '.workflow-steps a');
    return [];
  },
  addEventListener: (name, fn) => {if (name === 'click') onClick = fn;}
};
class MutationObserver {constructor(fn) {sync = fn;} observe() {}}
const window = {scrollTo: options => {
  assert.equal(options.top, 0); scrolled++;
}};
vm.runInNewContext(SOURCE, {document, window, MutationObserver});
const event = {
  // 也覆盖点到按钮内部子元素的情况。
  target: {closest: selector => selector === '#workflow_library_link' ? elements.workflow_library_link : null},
  preventDefault: () => prevented++
};
assert.equal(elements.workflow_result.hidden, false);
onClick(event);
assert.deepEqual(clicks, ['library']);
assert.equal(scrolled, 1);
assert.equal(prevented, 1);
// 仅解析完成时应打开日志，不能仍然跳资源库。
progress.textContent = '预解析已完成';
sync();
assert.equal(elements.workflow_library_link.textContent, '查看解析日志 →');
onClick(event);
assert.deepEqual(clicks, ['library', 'logs']);
// 下一次设置变化不应改变上一次完成结果对应的目的地。
summary.textContent = '下一次准备生成';
sync();
onClick(event);
assert.equal(clicks.at(-1), 'logs');
// 找不到标签或标签禁用时安全退出。
logs.disabled = true;
onClick(event);
delete selectors['#studio_tabs [role="tablist"] button[role="tab"][data-tab-id="tab_logs"]'];
onClick(event);
assert.equal(clicks.length, 3);
assert.equal(scrolled, 3);
'''.replace('SOURCE', json.dumps(source))
        result = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
