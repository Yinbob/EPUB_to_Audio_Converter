# 待人工标注的 MiMo 样本

编辑 [annotation.csv](annotation.csv)，按拼接、一致性、内容完整性的顺序试听。所有判断初始为空；填写 yes/no/uncertain/not_applicable，空白表示未检查。正常角色切换不算音色漂移；缺少同角色参考时填 uncertain 或 not_applicable，不凭单段判断跨段一致性。

review_status 使用 pending/reviewed/needs_review。已完成需填写 reviewer 和含时区的 ISO reviewed_at，例如 2026-10-16T12:00:00+08:00；notes 记录问题秒数和文字。

边界四列 click/cutoff/overlap/gap 全部明确判断后才能标 reviewed；labels_json 用 JSON 数组，对应 boundary_click_suspected/cutoff_suspected/overlap/unexpected_gap。只有四项都 no 才填 []。有疑点保持 needs_review，不把未知当正常。完整片段的 labels_json 留空。

人工结果用 import-review 导入，未标注记录不会进入训练；导出不自动划分 train/dev/test。相同 group_id 的所有变体应保留在同一划分。本包只提供材料，不证明检测或修复效果；章节、父块、修复子块、窗口音频相互重叠，不能按文件数统计独立样本。scope_kind 与 parent_chunk_id 标明修复子块及新增内部接缝；这些受保护字段不要修改。

### C000005_001 · 完整片段 · bryce_father

[试听](audio/C000005_001.wav)

原文：“What are you doing? You're getting mud everywhere!”

预期读法：“What are you doing? You're getting mud everywhere!”

### C000005_002 · 完整片段 · narrator

[试听](audio/C000005_002.wav)

原文： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

预期读法： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

### C000005_003 · 完整片段 · juli

[试听](audio/C000005_003.wav)

原文：“Don't you want some help?”

预期读法：“Don't you want some help?”

### C000005_004 · 完整片段 · narrator

[试听](audio/C000005_004.wav)

原文： She glanced my way. 

预期读法： She glanced my way. 

### C000005_005 · 完整片段 · juli

[试听](audio/C000005_005.wav)

原文：“It sure looks like you need it.”

预期读法：“It sure looks like you need it.”

### B000005_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_001.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“What are you doing? You're getting mud everywhere!” ｜  So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

预期读法：“What are you doing? You're getting mud everywhere!” ｜  So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

### B000005_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_002.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet.  ｜ “Don't you want some help?”

预期读法： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet.  ｜ “Don't you want some help?”

### B000005_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_003.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Don't you want some help?” ｜  She glanced my way. 

预期读法：“Don't you want some help?” ｜  She glanced my way. 

### B000005_004 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_004.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： She glanced my way.  ｜ “It sure looks like you need it.”

预期读法： She glanced my way.  ｜ “It sure looks like you need it.”
