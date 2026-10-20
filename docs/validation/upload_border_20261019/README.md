# 上传区虚线边框裁切修复（2026-10-19）

用户反馈上传区蓝色虚线两侧被白色遮盖。源码确认 Gradio `group/Index.svelte` 在 Group 及其直接 `.styler` 上都设置 `overflow: hidden`；此前桌面上传区左右各扩 8px 时只放开 form，遗漏 `.styler` 的裁切。

`workflow.py` 的 CSS 为 `#book_setup > .styler:has(.book-file-upload)` 与 `#book_setup .form:has(> .book-file-upload)` 设置 `overflow: visible !important`、透明背景，并将 form 放行规则移出桌面媒体查询。空上传态 `.book-file-upload:not(:has(.file-preview))` 同样允许溢出；上传文件后保留组件根部原有裁切与 FilePreview 内滚动。保留桌面左右各扩 8px、旧版 1280px／1320px 容器宽度及完整动画。

workflow 定向检查 14 项全部通过，见 `/tmp/upload_border_focus.log`；一次布局检测结果为 `[]`，见 `/tmp/upload_border_detector.json`；`git diff --check` 通过。独立 reviewer `narration_voice_finish` 的源码 disposition 为 **ship**。既有 localhost 浏览器拒绝未绕过，无新截图或实际视觉验收，不将源码判断描述为页面实测。

确认无 spawn 任务且仅有本地 TCP 连接后，终止旧服务 PID 89355，新进程 PID 90583 已监听原地址 `127.0.0.1:7862`，`/tmp/upload_border_server.log` 无启动错误。服务已加载修复，但启动证据不等于视觉通过；已打开页面需刷新。无新模型请求、音频生成或数据变更。

本次文档收尾仅新建本记录并追加工作流 surface，未修改源码或运行验证、服务、浏览器、API。
