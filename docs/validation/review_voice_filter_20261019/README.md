# 逐段核对的配置音色检索（2026-10-19）

用户反馈第 11 章前面男声、后面女声，要求逐段校对可按声音检索。当前项目的第 11 章配置为：Bryce 69 段使用 clone、Juli 9 段 Chloe、祖父 38 段 Dean、父亲 21 段 Dean、母亲 5 段 Mia、独立 narrator 32 段 Chloe；生成的 reading_plan 也包含 32 个独立 narrator 单位。见已有 [chapter11_diagnosis.json](chapter11_diagnosis.json)。这些是归属与声音配置诊断，不是音频声纹识别或听感复测；本轮不修改该诊断、角色项目、归属或音频。

## 新增行为

`role_voices.py` 的音色身份与选项按提供商及 preset 音色、clone 指纹或 design 描述分组，忽略角色 ID 与语速，使共用同一配置音色的人物段落可一起检索。界面增加可输入搜索的音色 Dropdown，与人物和范围筛选组合使用；当前表格中的未保存参数也参与筛选，但筛选本身不保存参数。

保存并进入下一段、合并、刷新及 `role_table.change` 后保持筛选。详情明确显示「配置音色」，不冒充从音频识别出的声音。原 filter 三项返回契约保留兼容，界面 wrapper 返回四项；保留每侧最多 300 字符的前后文、主题与共享菜单层级。

## 验证与边界

定向检查 43 项通过，见 `/tmp/review_voice_filter_tests.log`，首次测试错误使用的按钮 ID 已纠正。完整回归 721 项中 691 通过、30 按环境跳过，见 `/tmp/review_voice_filter_full_tests.log`。`git diff --check` 通过；一次检测仅提示历史进度条的 `width transition`，见 `/tmp/review_voice_filter_scan.json`。独立 reviewer `narration_voice_finish` 的源码 disposition 为 **ship**。

空闲服务由 PID 1931 重启为 PID 2901，已监听原端口 7862，当次 `/tmp/review_voice_filter_server.log` 为空，仅为启动证据。既有浏览器访问拒绝未绕过，无视觉确认、模型调用、音频生成或项目修改。

用户刷新页面后，可进入「逐段核对」，组合 Chloe 音色与 Narrator 人物定位上述 32 段配置为女声的叙述；列表可能同时包含其他已保存章节，需按带章号的段落标签核对第 11 章。此路径用于人工检查，不自动判定或更改归属。

本次文档收尾仅新建本记录并追加工作流 surface，未修改源码、诊断或项目，未运行测试、服务、API、浏览器。
