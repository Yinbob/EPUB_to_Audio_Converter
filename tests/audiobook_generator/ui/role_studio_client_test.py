"""执行实际状态同步脚本；用内存 DOM 替身检查逻辑，不替代浏览器视觉验收。"""
import json
import shutil
import subprocess
import unittest

from audiobook_generator.ui.role_studio import ROLE_SPLIT_HEAD


@unittest.skipUnless(shutil.which('node'), '客户端脚本检查需要 Node')
class RoleStudioClientTest(unittest.TestCase):
    def test_confirmation_follows_backend_and_resets_when_settings_change(self):
        source = ROLE_SPLIT_HEAD.removeprefix('<script>').removesuffix('</script>')
        harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const attributes = {};
const button = {disabled: false, dataset: {}, setAttribute: (key, value) => attributes[key] = value};
const probe = {dataset: {confirmed: '0'}};
const studio = {};
let mutation, options, tick;
const document = {readyState: 'complete', addEventListener() {}, querySelector(selector) {
  return {'#role_confirm_btn': button, '#role_confirmation_probe': probe, '#role_studio': studio}[selector] || null;
}};
class MutationObserver {
  constructor(fn) {mutation = fn;}
  observe(root, config) {assert.equal(root, studio); options = config;}
  disconnect() {}
}
vm.runInNewContext(SOURCE, {document, MutationObserver, setInterval: fn => {tick = fn;}, Date});
assert.equal(button.dataset.roleConfirmState, 'idle');
button.disabled = true;
mutation();
assert.equal(button.dataset.roleConfirmState, 'pending');
assert.equal(attributes['aria-busy'], 'true');
// 后台失败，恢复可点但不显示成功。
button.disabled = false;
mutation();
assert.equal(button.dataset.roleConfirmState, 'idle');
// 只有后台探针确认才出现成功；再次确认仍先进入等待。
probe.dataset.confirmed = '1';
mutation();
assert.equal(button.dataset.roleConfirmState, 'confirmed');
assert.match(attributes['aria-label'], /已确认/);
button.disabled = true;
mutation();
assert.equal(button.dataset.roleConfirmState, 'pending');
button.disabled = false;
mutation();
assert.equal(button.dataset.roleConfirmState, 'confirmed');
// 修改参数产生未确认探针，成功状态必须撤回。
probe.dataset.confirmed = '0';
mutation();
assert.equal(button.dataset.roleConfirmState, 'idle');
assert.equal(attributes['aria-busy'], 'false');
assert.equal(attributes['aria-label'], '确认剧本与角色参数');
assert(!options.attributeFilter.includes('aria-label'), '自身写入不可形成观察循环');
tick();
'''.replace('SOURCE', json.dumps(source))
        result = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
