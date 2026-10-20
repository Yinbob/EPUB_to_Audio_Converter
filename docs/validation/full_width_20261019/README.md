# 恢复全宽工作区（2026-10-19）

用户进一步明确要求恢复覆盖全屏，否定上一轮 1280px／1320px 的居中宽度上限。本轮全宽方案取代[上一轮大屏宽度方案](../wide_layout_20261019/README.md)，保留其历史验证记录。

## 源码修改

`web_ui.py` 的 `html .gradio-container` 使用 `width: 100% !important`、`max-width: none !important` 及 `box-sizing: border-box`；保留 `margin: 0 auto !important`，内边距为 `0 clamp(14px, 4vw, 48px) 64px !important`，宽度跟随窗口且内边距计入总宽。删除底部 1280px／1320px 大屏限宽断点。`workflow.py` 注释同步为由主样式管理全宽布局，先前的 1180px 覆盖规则继续保持删除。

保留原有主题、动画与小屏适配；顶栏继续与卡片同宽，高级弹窗 760px 等局部上限不改。全宽指主工作区随视口伸展，同时保留上述边距。

## 验证及边界

- workflow 与 theme 定向测试 24 项全部通过，见 `/tmp/full_width_focus.log`。
- 一次布局静态检测结果为 `[]`，见 `/tmp/full_width_detector.json`；`git diff --check` 通过。
- 独立源码 reviewer `narration_voice_finish` 的 disposition 为 **ship**，仅限本轮源码。
- 浏览器此前已拒绝 localhost 访问，本轮未绕过，没有浏览器视觉实测或新截图；测试与源码复核不等于实际页面验收。

确认无 spawn 子任务且 TCP 连接仅在本地后，重启空闲服务，旧 PID 88290 替换为新 PID 88829。新进程已确认监听 `127.0.0.1:7862`，`/tmp/full_width_server.log` 无启动错误；监听仅证明服务启动。已打开页面需刷新加载新样式。没有模型调用、音频生成或用户数据改动。

本次文档收尾仅新建本记录、标注上一方案已取代并追加工作流 surface，未修改源码或运行测试、服务、浏览器、API。

## 同日后续：已被指定版本恢复方案取代

用户随后明确授权恢复 `63aa489` 观感并适当加宽上传区，取代本记录的全宽方案。当前源码恢复 1280px／1320px 居中断点与旧版 hero、上传高度，另在桌面左右各拓宽上传区 8px，见[当前验证记录](../restore_63_layout_20261019/README.md)。上文全宽参数与 PID 88829 仅为当时历史；新服务 PID 89355 已监听原地址，仍无浏览器视觉验收。
