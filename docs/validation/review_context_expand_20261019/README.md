# 人物名称检索与扩展上下文（2026-10-19）

用户希望按姓名检索，并在逐段核对时看到更多上下文。人物 Dropdown 原已支持名称过滤且事件接线完整；本轮将标签明确为「按人物名称检索」，提示输入姓名后选择人物查看对应段落，也可仅查看对白，不更改筛选接口。

`review_context.py` 的上下文裁剪参数调整为 `MIN=180`、`MAX=300`，前后每侧最多 300 字符，另可附省略号，优先句界及英文词界，段落以换行相接；仍按同章 segment ID 定位。`web_ui.py` 的上下文面板使用默认折叠的原生 `details`，依次提供前文、加粗显示的当前完整原文、后文，全部 HTML 转义。字符上限是源码行为，不是页面可见行数。

中文／英文长度、词界、换行、重复句定位、转义、筛选保持及 UI 接线测试共 34 项全部通过，见 `/tmp/review_context_expand_tests.log`；日志中包含预设模拟保存失败的 traceback，但测试 suite 为 OK。`git diff --check` 通过；一次检测仅提示历史进度条 `width transition`，见 `/tmp/review_context_expand_scan.json`。独立 reviewer `narration_voice_finish` 的源码 disposition 为 **ship**。

确认服务空闲、无 spawn 子任务或外部连接后，由 PID 97200 重启为 PID 97765，已监听原端口 7862，当次 `/tmp/review_context_expand_server.log` 启动为空，仅为启动证据。需刷新已打开页面。既有浏览器访问拒绝未绕过，无浏览器／HTTP 视觉验收、API 请求、音频生成或项目数据更改。

本次文档收尾仅新建本记录并追加工作流 surface，未修改源码或运行测试、服务、浏览器、API。
