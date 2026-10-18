# 待人工标注的 MiMo 样本

编辑 [annotation.csv](annotation.csv)，按拼接、一致性、内容完整性的顺序试听。所有判断初始为空；填写 yes/no/uncertain/not_applicable，空白表示未检查。正常角色切换不算音色漂移；缺少同角色参考时填 uncertain 或 not_applicable，不凭单段判断跨段一致性。

review_status 使用 pending/reviewed/needs_review。已完成需填写 reviewer 和含时区的 ISO reviewed_at，例如 2026-10-16T12:00:00+08:00；notes 记录问题秒数和文字。

边界四列 click/cutoff/overlap/gap 全部明确判断后才能标 reviewed；labels_json 用 JSON 数组，对应 boundary_click_suspected/cutoff_suspected/overlap/unexpected_gap。只有四项都 no 才填 []。有疑点保持 needs_review，不把未知当正常。完整片段的 labels_json 留空。

人工结果用 import-review 导入，未标注记录不会进入训练；导出不自动划分 train/dev/test。相同 group_id 的所有变体应保留在同一划分。本包只提供材料，不证明检测或修复效果；章节、父块、修复子块、窗口音频相互重叠，不能按文件数统计独立样本。scope_kind 与 parent_chunk_id 标明修复子块及新增内部接缝；这些受保护字段不要修改。

### C000001_001 · 完整片段 · narrator

[试听](audio/C000001_001.wav)

原文：On October 16, 2026, the report showed an increase of 3.5%.

预期读法：On October 16, 2026, the report showed an increase of 3.5%.

### C000001_002 · 完整片段 · narrator

[试听](audio/C000001_002.wav)

原文：The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

预期读法：The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

### B000001_001 · 同一角色

[接缝试听](audio/B000001_001.wav) · [完整上下文](audio/chapter_000001_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：On October 16, 2026, the report showed an increase of 3.5%. ｜ The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

预期读法：On October 16, 2026, the report showed an increase of 3.5%. ｜ The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

### C000002_001 · 完整片段 · narrator

[试听](audio/C000002_001.wav)

原文：On October 16, 2026, the report showed an increase of 3.5%.

预期读法：On October 16, 2026, the report showed an increase of 3.5%.

### C000002_002 · 完整片段 · narrator

[试听](audio/C000002_002.wav)

原文：The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

预期读法：The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

### B000002_001 · 同一角色

[接缝试听](audio/B000002_001.wav) · [完整上下文](audio/chapter_000002_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：On October 16, 2026, the report showed an increase of 3.5%. ｜ The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.

预期读法：On October 16, 2026, the report showed an increase of 3.5%. ｜ The 21st runner carried 24 cards, while the 3rd runner carried 18 cards.
