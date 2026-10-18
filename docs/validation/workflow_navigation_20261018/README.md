# 完成提示跳转修复 · 2026-10-18

问题：生成完成后顶部「前往资源库试听与下载」按钮无响应。

原因：完成提示的客户端代码依赖 `#studio_tabs > .tab-nav button`，而已安装的 Gradio 5.50.0 前端使用 `.tab-wrapper`、`.tab-container`、`role="tablist"`。旧选择器没有找到目标。

修复：在主标签区域按 `role="tablist"` 和按钮的 `data-tab-id` 定位，调用原生标签点击以保留 Gradio 切页及资源库刷新事件。普通生成进入 `tab_library`，仅解析进入 `tab_logs`；切页后平滑回到顶部。不存在或禁用的标签安全退出。未改页面布局、样式及合成逻辑。

验证：Node VM 执行实际 WORKFLOW_HEAD_HTML，覆盖资源库、日志、按钮子元素点击、禁用／缺失标签，以及完成结果保留；连同既有 workflow_wiring_test 共 10 项通过。日志见 tests.log。已对照本地已安装 Gradio 前端的 role/data-tab-id 输出；本次没有浏览器页面访问或截图，不声称已实测浏览器点击。

未执行模型请求。服务无合成子进程后重新加载；页面需要刷新。
