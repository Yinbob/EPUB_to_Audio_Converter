# 章节范围控件与共享菜单层级（2026-10-19）

用户报告章节目录下拉仍被起始／输出文字盖住，要求统一修复以避免复发，并放大或调整控件形式。本轮集中菜单层级规则，同时扩大章节范围选择面。

## 源码修改

`web_ui.py` 将 `.app-card` 菜单祖先及高级弹窗内部菜单祖先的层级，由固定 `2` 改为 `calc(var(--layer-top, 100) + 1)`，全站 `.gradio-container ul.options` 菜单自身使用对应 `+ 2` 层级。保留卡片 `20`、仅在非弹窗态提升主 tabs 的规则、顶栏 `100` 与弹窗 `1000`；不改 fixed 定位或 `.modal-scroll` 自身滚动。`role_studio.py` 删除上一轮局部层级覆盖，只保留外观，由共用规则统一管理。

章节范围行改为起始／结束两个 Column，使用独立外置 HTML 标题。Dropdown 隐藏浮动标签，但保留 `label` 对应的无障碍名称；名称搜索、原组件 ID、数据和事件接口不变。源码输入面最小高度 72px、输入及独立标题字号 1rem、两端间距 24px、圆角 16px、选项最小高度 44px；深浅主题使用既有变量，窄屏上下排列，保留原动画。这些是源码参数，不是实际页面测量。

## 验证与边界

workflow_wiring、chapters、theme、ambient、role_studio 相关测试 56 项全部通过，见 `/tmp/chapter_range_layers_test.log`。旧 progress_wiring 的相关断言由固定 `z-index: 2` 更新为共享层级契约，在现有 `venv_audio_quality` 中仅于内存解除环境 skip，菜单展开、弹窗层级、弹窗滚动 3 项全部通过，见 `/tmp/chapter_range_legacy_layers_test.log`。本轮没有重新运行此前 712 项全量回归，不沿用其结果作为本轮证据。

一次静态检测仅提示历史主进度条的 `width transition`，见 `/tmp/chapter_range_layers_scan.json`；`git diff --check` 与 Python 编译检查通过。独立 reviewer `chapter_finish_reviewer` 最终将问题评为 **resolved**，源码 disposition 为 **ship**；此前要求修正的旧测试断言已更新并验证，不含页面观感验收。

既有 localhost 浏览器拒绝不得绕过，本轮无浏览器、截图、真实 API、新音频或项目内容修改，实际视觉与交互仍未验收。确认无 spawn 子任务及外部连接后，服务由 PID 94729 重启为 PID 96119，已监听原端口 7862；截至启动检查 traceback 为 0，仅为启动证据。需刷新所有旧项目标签页，不能将服务监听等同于页面已更新。

本次文档收尾仅新建本记录、追加工作流 surface，并澄清 surface 中原文保持显示、仅新增上下文折叠；未改全站 `DESIGN.md`／`PRODUCT.md`、源码，未运行测试、浏览器、服务或 API。
