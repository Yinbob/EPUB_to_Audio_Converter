# 英语三角色选角先导：正文与归属待审

这是助手自编的单来源先导材料，尚未合成，也没有听众辨识结果。人物归属都是 proposed，未代填人工通过。

## 填写顺序

1. 先核对下列角色设定、逐句归属及英文表达；可直接在聊天回复需要调整的句号。
2. 正文确定后，再根据已核验 Mia／Chloe 探针评价角色声音适配；当前适配表保持空白。
3. 固定正文与条件后合成；先质检和人工试听，再导出盲化辨识材料。

人工表：[human_review.pending.json](human_review.pending.json)。可直接在聊天反馈，由助手按原话回填并保留版本。

已核验声音参考：[Mia 样本一](../english_20261016/E01_Mia.wav)、[Mia 样本二](../english_20261016/E02_Mia.wav)、[Chloe 样本一](../english_20261016/E03_Chloe.wav)、[Chloe 样本二](../english_20261016/E04_Chloe.wav)。请先审正文；声音适配可以后填。

## 角色设定

- Alex（alex）：推动行动并提出下一步安排；不预设性别、年龄或音高。
- Blair（blair）：核对地图与细节，并与 Alex 反复交流；不预设性别、年龄或音高。
- Casey（casey）：提供钥匙和入门方法；不预设性别、年龄或音高。

## 场景 1：At the bridge

**S01U01 · Alex**：The path beside the river is covered with water, so we should cross the old bridge before sunset.

**S01U02 · Blair**：I checked the map this morning, and the wooden steps on the far side should lead us to the house.

**S01U03 · Alex**：Then keep the lantern inside your bag until we reach the trees, where the light will be harder to see.

**S01U04 · Casey**：I will bring the small key from the boat and meet you at the gate beside the stone wall.

## 场景 2：Beside the gate

**S02U01 · Blair**：The front gate is closed, but there is a narrow opening between the garden shed and the wall.

**S02U02 · Casey**：That opening leads to the kitchen door, and the key should turn easily if you lift the handle first.

**S02U03 · Blair**：We should leave the lantern here for a moment, because the glass might break if we climb with it.

**S02U04 · Alex**：I can hold the bag while you climb over, and then pass it through the opening near the ground.

## 场景 3：Inside the house

**S03U01 · Alex**：There is a folded letter under the empty cup, but the writing is too faint to read in this light.

**S03U02 · Blair**：Bring it closer to the window and keep the edges flat, so the paper does not tear along the fold.

**S03U03 · Alex**：The first line mentions a room upstairs, and the last line asks us to wait until the morning.

**S03U04 · Blair**：Then we should close the door quietly and leave the letter here, exactly where we found it beside the cup.

## 离线分配检查

三角色、两种声音必然存在共享；所有条件正文、顺序、停顿、速度与指令一致，只改变声音。

| 策略（固定 seed=42） | Alex | Blair | Casey | 同一互动图上的声纹代理值（越低越好） |
|---|---|---|---|---|
| interaction | Mia | Chloe | Mia | 1.530144 |
| global | Chloe | Mia | Chloe | 1.530144 |
| random | Mia | Chloe | Mia | 1.530144 |

角色相邻切换：Alex–Blair 6 次、Alex–Casey 1 次、Blair–Casey 2 次。跨场景不连边。

互动图（interaction）与随机（random）分配完全相同；全局（global）仅互换声音，仍由 Alex／Casey 共享声音。三者当前代理值相同，**没有展示出互动图策略优势**。不更换随机种子以追求有利差异。

各策略自己的 objective 使用的边权不同，不可横向比较；上表另按同一原始互动图计算。

0 个听众、0 次新增合成；该数值不是辨识正确率。不得据此声称某策略更容易听懂。

## 后续执行边界

适配基线需要先补全人工表；不以中性占位值冒充属性匹配。角色锁定仅做离线约束检验，未修改真实锁定。
首次合成前保存最终正文与声音库指纹。合成后不自动套用中文样本的 100ms 增益方案；英语接缝需要单独核验。
单句时长尚未知；不足 3 秒的辨识片段不应通过现有导出门禁。三场景属于同一自编来源，不作为独立书目切分。
实验用途为前期可行性与材料检查，正式收益验证仍需更多独立文本和听众。

当前只有两种已核验声音，无法检验多声音距离排序的收益。待更多英语声音通过核验后，可在固定材料上重新分配；也可预先登记多组不同互动结构作稳健性比较。不能仅挑出有利文本或随机种子报告。正式对照仍需人工适配表、质量合格的实际音频以及独立听众。

离线证据及各条件计划：[offline_validation.json](../../audiobook_output/casting_english_plan_20261016/offline_validation.json)。这些计划是待审材料，普通角色规划器可能重新分配重复声音；实际实验必须使用选角后的固定计划，并在请求前再次核对正文和声音，不能直接把初始 proposed 剧本当作实验条件。
