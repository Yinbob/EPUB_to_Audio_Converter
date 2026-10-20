# 恢复 63aa489 布局观感并拓宽上传区（2026-10-19）

用户明确指定恢复 `63aa489` 的观感，同时适当加宽文件上传区。本轮取代[全宽方案](../full_width_20261019/README.md)，只恢复指定布局参数，不回退新增章节、角色、导航、既有修复或动画等业务与交互能力。

## 源码修改

- `web_ui.py` 容器恢复 `.gradio-container` 居中选择器，撤销 `html` 高特异性及 `max-width: none`，保留 `width: 100%`、`box-sizing: border-box` 与 `0 clamp(14px, 4vw, 48px) 64px` 内边距。恢复视口至少 1200px 时最大宽度 1280px、至少 1440px 时最大宽度 1320px 的断点。
- `workflow.py` 删除 hero 的 `18px 8px 12px` 内边距及段落 `65ch` 覆盖，使主样式既有的顶部 `clamp` 18～30px、底部 24px 及段落最大宽度 560px 生效。删除上传区 180px 高度覆盖，恢复主样式 300px。
- 视口至少 720px 时，`#book_setup .book-file-upload` 使用 `width: calc(100% + 16px)`、`max-width: none`、`margin-inline: -8px`，左右各拓宽 8px，仍保留卡片约 16px 内边距；直接父 `.form` 放行溢出，避免裁切。窄屏不扩宽。

保留主题、完整动态及新功能；上述是源码参数恢复与局部上传区扩宽，不是整仓版本回退或已完成的视觉对照。

## 验证与加载

workflow、theme、chapters 定向测试 30 项全部通过，见 `/tmp/restore_63_layout_focus.log`；一次布局静态检测结果为 `[]`，见 `/tmp/restore_63_layout_detector.json`；`git diff --check` 通过。独立 reviewer `narration_voice_finish` 的源码 disposition 为 **ship**，未发现上传宽度与 form 布局阻断。

浏览器此前已明确拒绝 localhost 访问，本轮未绕过，没有实际页面视觉验收或新截图。测试、源码复核及指定版本参数对照不证明实际屏幕观感已获确认。

确认空闲服务无 spawn 子任务且 TCP 连接仅在本地后，向旧 PID 88829 发送 TERM，并在原地址启动新进程 PID 89355；已确认监听 `127.0.0.1:7862`，`/tmp/restore_63_layout_server.log` 无启动错误，仅为服务启动证据。已打开页面需刷新加载样式。无模型请求、音频生成或用户数据修改。

本次文档收尾仅新建本记录、标注全宽方案已取代并追加工作流 surface，未修改源码或运行测试、服务、浏览器、API。
