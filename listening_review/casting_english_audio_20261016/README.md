# 待人工标注的 MiMo 样本

编辑 [annotation.csv](annotation.csv)，按拼接、一致性、内容完整性的顺序试听。所有判断初始为空；填写 yes/no/uncertain/not_applicable，空白表示未检查。正常角色切换不算音色漂移；缺少同角色参考时填 uncertain 或 not_applicable，不凭单段判断跨段一致性。

review_status 使用 pending/reviewed/needs_review。已完成需填写 reviewer 和含时区的 ISO reviewed_at，例如 2026-10-16T12:00:00+08:00；notes 记录问题秒数和文字。

边界四列 click/cutoff/overlap/gap 全部明确判断后才能标 reviewed；labels_json 用 JSON 数组，对应 boundary_click_suspected/cutoff_suspected/overlap/unexpected_gap。只有四项都 no 才填 []。有疑点保持 needs_review，不把未知当正常。完整片段的 labels_json 留空。

人工结果用 import-review 导入，未标注记录不会进入训练；导出不自动划分 train/dev/test。相同 group_id 的所有变体应保留在同一划分。本包只提供材料，不证明检测或修复效果；章节、父块、修复子块、窗口音频相互重叠，不能按文件数统计独立样本。scope_kind 与 parent_chunk_id 标明修复子块及新增内部接缝；这些受保护字段不要修改。

### C000001_001 · 完整片段 · alex

[试听](audio/C000001_001.wav)

原文：The path beside the river is covered with water, so we should cross the old bridge before sunset.


预期读法：The path beside the river is covered with water, so we should cross the old bridge before sunset.


### C000001_002 · 完整片段 · blair

[试听](audio/C000001_002.wav)

原文：I checked the map this morning, and the wooden steps on the far side should lead us to the house.


预期读法：I checked the map this morning, and the wooden steps on the far side should lead us to the house.


### C000001_003 · 完整片段 · alex

[试听](audio/C000001_003.wav)

原文：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


预期读法：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


### C000001_004 · 完整片段 · casey

[试听](audio/C000001_004.wav)

原文：I will bring the small key from the boat and meet you at the gate beside the stone wall.

预期读法：I will bring the small key from the boat and meet you at the gate beside the stone wall.

### B000001_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000001_001.wav) · [完整上下文](audio/chapter_000001_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The path beside the river is covered with water, so we should cross the old bridge before sunset.
 ｜ I checked the map this morning, and the wooden steps on the far side should lead us to the house.


预期读法：The path beside the river is covered with water, so we should cross the old bridge before sunset.
 ｜ I checked the map this morning, and the wooden steps on the far side should lead us to the house.


### B000001_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000001_002.wav) · [完整上下文](audio/chapter_000001_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：I checked the map this morning, and the wooden steps on the far side should lead us to the house.
 ｜ Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


预期读法：I checked the map this morning, and the wooden steps on the far side should lead us to the house.
 ｜ Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


### B000001_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000001_003.wav) · [完整上下文](audio/chapter_000001_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.
 ｜ I will bring the small key from the boat and meet you at the gate beside the stone wall.

预期读法：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.
 ｜ I will bring the small key from the boat and meet you at the gate beside the stone wall.

### C000002_001 · 完整片段 · blair

[试听](audio/C000002_001.wav)

原文：The front gate is closed, but there is a narrow opening between the garden shed and the wall.


预期读法：The front gate is closed, but there is a narrow opening between the garden shed and the wall.


### C000002_002 · 完整片段 · casey

[试听](audio/C000002_002.wav)

原文：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


预期读法：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


### C000002_003 · 完整片段 · blair

[试听](audio/C000002_003.wav)

原文：We should leave the lantern here for a moment, because the glass might break if we climb with it.


预期读法：We should leave the lantern here for a moment, because the glass might break if we climb with it.


### C000002_004 · 完整片段 · alex

[试听](audio/C000002_004.wav)

原文：I can hold the bag while you climb over, and then pass it through the opening near the ground.

预期读法：I can hold the bag while you climb over, and then pass it through the opening near the ground.

### B000002_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000002_001.wav) · [完整上下文](audio/chapter_000002_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The front gate is closed, but there is a narrow opening between the garden shed and the wall.
 ｜ That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


预期读法：The front gate is closed, but there is a narrow opening between the garden shed and the wall.
 ｜ That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


### B000002_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000002_002.wav) · [完整上下文](audio/chapter_000002_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.
 ｜ We should leave the lantern here for a moment, because the glass might break if we climb with it.


预期读法：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.
 ｜ We should leave the lantern here for a moment, because the glass might break if we climb with it.


### B000002_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000002_003.wav) · [完整上下文](audio/chapter_000002_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：We should leave the lantern here for a moment, because the glass might break if we climb with it.
 ｜ I can hold the bag while you climb over, and then pass it through the opening near the ground.

预期读法：We should leave the lantern here for a moment, because the glass might break if we climb with it.
 ｜ I can hold the bag while you climb over, and then pass it through the opening near the ground.

### C000003_001 · 完整片段 · alex

[试听](audio/C000003_001.wav)

原文：There is a folded letter under the empty cup, but the writing is too faint to read in this light.


预期读法：There is a folded letter under the empty cup, but the writing is too faint to read in this light.


### C000003_002 · 完整片段 · blair

[试听](audio/C000003_002.wav)

原文：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


预期读法：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


### C000003_003 · 完整片段 · alex

[试听](audio/C000003_003.wav)

原文：The first line mentions a room upstairs, and the last line asks us to wait until the morning.


预期读法：The first line mentions a room upstairs, and the last line asks us to wait until the morning.


### C000003_004 · 完整片段 · blair

[试听](audio/C000003_004.wav)

原文：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

预期读法：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

### B000003_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000003_001.wav) · [完整上下文](audio/chapter_000003_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：There is a folded letter under the empty cup, but the writing is too faint to read in this light.
 ｜ Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


预期读法：There is a folded letter under the empty cup, but the writing is too faint to read in this light.
 ｜ Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


### B000003_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000003_002.wav) · [完整上下文](audio/chapter_000003_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.
 ｜ The first line mentions a room upstairs, and the last line asks us to wait until the morning.


预期读法：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.
 ｜ The first line mentions a room upstairs, and the last line asks us to wait until the morning.


### B000003_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000003_003.wav) · [完整上下文](audio/chapter_000003_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The first line mentions a room upstairs, and the last line asks us to wait until the morning.
 ｜ Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

预期读法：The first line mentions a room upstairs, and the last line asks us to wait until the morning.
 ｜ Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

### C000004_001 · 完整片段 · alex

[试听](audio/C000004_001.wav)

原文：The path beside the river is covered with water, so we should cross the old bridge before sunset.


预期读法：The path beside the river is covered with water, so we should cross the old bridge before sunset.


### C000004_002 · 完整片段 · blair

[试听](audio/C000004_002.wav)

原文：I checked the map this morning, and the wooden steps on the far side should lead us to the house.


预期读法：I checked the map this morning, and the wooden steps on the far side should lead us to the house.


### C000004_003 · 完整片段 · alex

[试听](audio/C000004_003.wav)

原文：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


预期读法：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


### C000004_004 · 完整片段 · casey

[试听](audio/C000004_004.wav)

原文：I will bring the small key from the boat and meet you at the gate beside the stone wall.

预期读法：I will bring the small key from the boat and meet you at the gate beside the stone wall.

### B000004_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000004_001.wav) · [完整上下文](audio/chapter_000004_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The path beside the river is covered with water, so we should cross the old bridge before sunset.
 ｜ I checked the map this morning, and the wooden steps on the far side should lead us to the house.


预期读法：The path beside the river is covered with water, so we should cross the old bridge before sunset.
 ｜ I checked the map this morning, and the wooden steps on the far side should lead us to the house.


### B000004_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000004_002.wav) · [完整上下文](audio/chapter_000004_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：I checked the map this morning, and the wooden steps on the far side should lead us to the house.
 ｜ Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


预期读法：I checked the map this morning, and the wooden steps on the far side should lead us to the house.
 ｜ Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


### B000004_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000004_003.wav) · [完整上下文](audio/chapter_000004_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.
 ｜ I will bring the small key from the boat and meet you at the gate beside the stone wall.

预期读法：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.
 ｜ I will bring the small key from the boat and meet you at the gate beside the stone wall.

### C000005_001 · 完整片段 · blair

[试听](audio/C000005_001.wav)

原文：The front gate is closed, but there is a narrow opening between the garden shed and the wall.


预期读法：The front gate is closed, but there is a narrow opening between the garden shed and the wall.


### C000005_002 · 完整片段 · casey

[试听](audio/C000005_002.wav)

原文：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


预期读法：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


### C000005_003 · 完整片段 · blair

[试听](audio/C000005_003.wav)

原文：We should leave the lantern here for a moment, because the glass might break if we climb with it.


预期读法：We should leave the lantern here for a moment, because the glass might break if we climb with it.


### C000005_004 · 完整片段 · alex

[试听](audio/C000005_004.wav)

原文：I can hold the bag while you climb over, and then pass it through the opening near the ground.

预期读法：I can hold the bag while you climb over, and then pass it through the opening near the ground.

### B000005_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_001.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The front gate is closed, but there is a narrow opening between the garden shed and the wall.
 ｜ That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


预期读法：The front gate is closed, but there is a narrow opening between the garden shed and the wall.
 ｜ That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


### B000005_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_002.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.
 ｜ We should leave the lantern here for a moment, because the glass might break if we climb with it.


预期读法：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.
 ｜ We should leave the lantern here for a moment, because the glass might break if we climb with it.


### B000005_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_003.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：We should leave the lantern here for a moment, because the glass might break if we climb with it.
 ｜ I can hold the bag while you climb over, and then pass it through the opening near the ground.

预期读法：We should leave the lantern here for a moment, because the glass might break if we climb with it.
 ｜ I can hold the bag while you climb over, and then pass it through the opening near the ground.

### C000006_001 · 完整片段 · alex

[试听](audio/C000006_001.wav)

原文：There is a folded letter under the empty cup, but the writing is too faint to read in this light.


预期读法：There is a folded letter under the empty cup, but the writing is too faint to read in this light.


### C000006_002 · 完整片段 · blair

[试听](audio/C000006_002.wav)

原文：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


预期读法：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


### C000006_003 · 完整片段 · alex

[试听](audio/C000006_003.wav)

原文：The first line mentions a room upstairs, and the last line asks us to wait until the morning.


预期读法：The first line mentions a room upstairs, and the last line asks us to wait until the morning.


### C000006_004 · 完整片段 · blair

[试听](audio/C000006_004.wav)

原文：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

预期读法：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

### B000006_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000006_001.wav) · [完整上下文](audio/chapter_000006_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：There is a folded letter under the empty cup, but the writing is too faint to read in this light.
 ｜ Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


预期读法：There is a folded letter under the empty cup, but the writing is too faint to read in this light.
 ｜ Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


### B000006_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000006_002.wav) · [完整上下文](audio/chapter_000006_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.
 ｜ The first line mentions a room upstairs, and the last line asks us to wait until the morning.


预期读法：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.
 ｜ The first line mentions a room upstairs, and the last line asks us to wait until the morning.


### B000006_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000006_003.wav) · [完整上下文](audio/chapter_000006_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The first line mentions a room upstairs, and the last line asks us to wait until the morning.
 ｜ Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

预期读法：The first line mentions a room upstairs, and the last line asks us to wait until the morning.
 ｜ Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

### C000007_001 · 完整片段 · alex

[试听](audio/C000007_001.wav)

原文：The path beside the river is covered with water, so we should cross the old bridge before sunset.


预期读法：The path beside the river is covered with water, so we should cross the old bridge before sunset.


### C000007_002 · 完整片段 · blair

[试听](audio/C000007_002.wav)

原文：I checked the map this morning, and the wooden steps on the far side should lead us to the house.


预期读法：I checked the map this morning, and the wooden steps on the far side should lead us to the house.


### C000007_003 · 完整片段 · alex

[试听](audio/C000007_003.wav)

原文：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


预期读法：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


### C000007_004 · 完整片段 · casey

[试听](audio/C000007_004.wav)

原文：I will bring the small key from the boat and meet you at the gate beside the stone wall.

预期读法：I will bring the small key from the boat and meet you at the gate beside the stone wall.

### B000007_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000007_001.wav) · [完整上下文](audio/chapter_000007_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The path beside the river is covered with water, so we should cross the old bridge before sunset.
 ｜ I checked the map this morning, and the wooden steps on the far side should lead us to the house.


预期读法：The path beside the river is covered with water, so we should cross the old bridge before sunset.
 ｜ I checked the map this morning, and the wooden steps on the far side should lead us to the house.


### B000007_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000007_002.wav) · [完整上下文](audio/chapter_000007_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：I checked the map this morning, and the wooden steps on the far side should lead us to the house.
 ｜ Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


预期读法：I checked the map this morning, and the wooden steps on the far side should lead us to the house.
 ｜ Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.


### B000007_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000007_003.wav) · [完整上下文](audio/chapter_000007_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.
 ｜ I will bring the small key from the boat and meet you at the gate beside the stone wall.

预期读法：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.
 ｜ I will bring the small key from the boat and meet you at the gate beside the stone wall.

### C000008_001 · 完整片段 · blair

[试听](audio/C000008_001.wav)

原文：The front gate is closed, but there is a narrow opening between the garden shed and the wall.


预期读法：The front gate is closed, but there is a narrow opening between the garden shed and the wall.


### C000008_002 · 完整片段 · casey

[试听](audio/C000008_002.wav)

原文：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


预期读法：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


### C000008_003 · 完整片段 · blair

[试听](audio/C000008_003.wav)

原文：We should leave the lantern here for a moment, because the glass might break if we climb with it.


预期读法：We should leave the lantern here for a moment, because the glass might break if we climb with it.


### C000008_004 · 完整片段 · alex

[试听](audio/C000008_004.wav)

原文：I can hold the bag while you climb over, and then pass it through the opening near the ground.

预期读法：I can hold the bag while you climb over, and then pass it through the opening near the ground.

### B000008_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000008_001.wav) · [完整上下文](audio/chapter_000008_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The front gate is closed, but there is a narrow opening between the garden shed and the wall.
 ｜ That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


预期读法：The front gate is closed, but there is a narrow opening between the garden shed and the wall.
 ｜ That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.


### B000008_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000008_002.wav) · [完整上下文](audio/chapter_000008_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.
 ｜ We should leave the lantern here for a moment, because the glass might break if we climb with it.


预期读法：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.
 ｜ We should leave the lantern here for a moment, because the glass might break if we climb with it.


### B000008_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000008_003.wav) · [完整上下文](audio/chapter_000008_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：We should leave the lantern here for a moment, because the glass might break if we climb with it.
 ｜ I can hold the bag while you climb over, and then pass it through the opening near the ground.

预期读法：We should leave the lantern here for a moment, because the glass might break if we climb with it.
 ｜ I can hold the bag while you climb over, and then pass it through the opening near the ground.

### C000009_001 · 完整片段 · alex

[试听](audio/C000009_001.wav)

原文：There is a folded letter under the empty cup, but the writing is too faint to read in this light.


预期读法：There is a folded letter under the empty cup, but the writing is too faint to read in this light.


### C000009_002 · 完整片段 · blair

[试听](audio/C000009_002.wav)

原文：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


预期读法：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


### C000009_003 · 完整片段 · alex

[试听](audio/C000009_003.wav)

原文：The first line mentions a room upstairs, and the last line asks us to wait until the morning.


预期读法：The first line mentions a room upstairs, and the last line asks us to wait until the morning.


### C000009_004 · 完整片段 · blair

[试听](audio/C000009_004.wav)

原文：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

预期读法：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

### B000009_001 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000009_001.wav) · [完整上下文](audio/chapter_000009_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：There is a folded letter under the empty cup, but the writing is too faint to read in this light.
 ｜ Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


预期读法：There is a folded letter under the empty cup, but the writing is too faint to read in this light.
 ｜ Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.


### B000009_002 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000009_002.wav) · [完整上下文](audio/chapter_000009_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.
 ｜ The first line mentions a room upstairs, and the last line asks us to wait until the morning.


预期读法：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.
 ｜ The first line mentions a room upstairs, and the last line asks us to wait until the morning.


### B000009_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000009_003.wav) · [完整上下文](audio/chapter_000009_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：The first line mentions a room upstairs, and the last line asks us to wait until the morning.
 ｜ Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

预期读法：The first line mentions a room upstairs, and the last line asks us to wait until the morning.
 ｜ Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.
