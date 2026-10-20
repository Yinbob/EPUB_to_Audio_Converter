# 上传框虚线颜色修复（2026-10-19）

用户反馈前次放行裁剪后，蓝色虚线左右变黑。源码发现 Gradio File 外层 Block 的虚线／基础边框与内部上传按钮自绘边框叠为两层；内层原先默认使用灰色 `--apple-border`，悬停才切蓝。本轮没有浏览器复现黑边，不能断言这就是唯一根因。

仅修改 `workflow.py`：`#book_setup .book-file-upload` 根部边框宽度设为 0、颜色透明；内部上传按钮使用 `box-sizing: border-box`，以独立长写属性设置 1.5px 虚线及 `var(--apple-blue)`，键盘 `focus-visible` 使用 2px 蓝色轮廓、偏移 4px。保留桌面左右各扩 8px、此前溢出修复、主题、完整悬停／点击动态及上传后预览。

workflow_wiring、theme、ambient 相关测试 43 项全部通过，见 `/tmp/upload_border_color_tests.log`；`git diff --check` 通过。一次静态检测退出码为 0、无输出，`/tmp/upload_border_color_scan.json` 为空，未报告缺陷；后续重复工具调用仅确认退出码，不将空文件称作可解析的 JSON 报告。独立 reviewer `narration_voice_finish` 的源码 disposition 为 **ship**。

浏览器此前拒绝访问 localhost，不得绕过，本轮未作视觉确认。确认无 spawn 或外部 TCP 任务后，停止旧服务 PID 96119，新 PID 96777 已监听原端口 7862；当次 `/tmp/upload_border_color_server.log` 为空，仅为服务启动证据，不代表边框视觉通过。已打开页面需刷新。没有 API 请求、音频生成或数据改动。

本次文档收尾仅新建本记录并追加工作流 surface，未修改源码或运行测试、浏览器、服务、API。

## 同日后续：按用户要求恢复原悬停效果

上节常蓝边框方案已按用户要求撤回。本轮删除 `workflow.py` 上轮全部 16 行外框边框清除、内部按钮常蓝、border-box 及焦点覆盖，保留上传区拓宽与溢出修复。通过 `git show` 脚本逐字比较，`web_ui.py` 上传区基础及 hover／active 段与 `63aa489` 一致：默认灰虚线，悬停经 0.25 秒转蓝、图标上移 3px，按下缩至 0.99；这是源码一致性证据，不是视觉确认。

现有 workflow 离线测试 15 项通过，见 `/tmp/upload_hover_restore_tests.log`；首次沙箱运行因 OMP 限制失败，随后在批准环境重跑通过。一次静态检测退出 0、无输出，见 `/tmp/upload_hover_restore_scan.json`；差异检查通过，独立 reviewer `narration_voice_finish` 源码 disposition 为 **ship**。确认服务空闲后由 PID 96777 重启为 PID 97200，已监听原端口 7862，当次 `/tmp/upload_hover_restore_server.log` 为空，仅为启动证据。无浏览器或 HTTP 视觉确认、模型请求及数据改动，需刷新已打开页面。本次文档收尾仅追加本记录与 surface，未修改源码或运行测试、服务、浏览器。
