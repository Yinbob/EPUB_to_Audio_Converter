# 大屏容器宽度恢复（2026-10-19）

**历史方案，已取代：**用户随后明确要求恢复全宽，否定此处 1280px／1320px 居中上限。当前源码与加载状态见[全宽方案](../full_width_20261019/README.md)；下文保留为当时修改和验证记录。

用户反馈大屏界面比原先窄，两侧留白过多。根因是 `audiobook_generator/ui/workflow.py` 的 `WORKFLOW_CSS` 在主样式后拼接，使用 `html .gradio-container { max-width: 1180px !important; }` 覆盖了既有大屏断点。

## 修改范围

仅删除该 1180px 限宽规则，补充由主样式管理页面宽度的注释。恢复使用 `web_ui.py` 的既有规则：视口至少 1200px 时容器最大宽度为 1280px，至少 1440px 时为 1320px；实际宽度仍受视口及原有内边距约束。保留居中、padding、小屏规则、主题和动画，没有另增布局或改动数据行为。

## 验证与限制

- 首次定向测试被 OMP 共享内存环境限制中断；在允许环境中重跑，24 项全部通过，见 `/tmp/wide_layout_focus.log`。
- 布局静态检测本轮仅运行一次，结果为 `[]`，见 `/tmp/wide_layout_detector.json`。
- `git diff --check` 通过；独立源码 reviewer `narration_voice_finish` 的 disposition 为 **ship**，仅限此次源码。
- 浏览器此前已拒绝 localhost 访问，本轮未绕过，无新页面截图或视觉验收；上述结果不能证明用户屏幕上的实际宽度或交互观感。

## 服务加载

此前《Flipped》首章任务已到 100／100，确认无 spawn 子进程和外部 TCP 连接后，向旧服务 PID 85773 发送 TERM，再在原地址启动服务。新进程 PID 88290 已确认监听 `127.0.0.1:7862`，启动日志无错误，记录为 `/tmp/wide_layout_server.log`。

此次重启一并加载[资源库点击焦点补充](../library_selection_style_20261019/README.md)及[弹出列表层级修复](../dropdown_layers_20261019/README.md)，更新了此前“待下次重启加载”的状态。服务启动与监听仅证明服务启动，不等于浏览器视觉实测；已打开页面仍需刷新加载新样式。本轮未调用模型、生成音频或修改用户数据。

本次文档收尾仅新建本记录、补充上述两份验证记录及工作流 surface，未修改源码、运行测试、服务或浏览器。
