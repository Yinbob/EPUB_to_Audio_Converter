# 英语三角色选角先导：角色、归属与适配已确认

这是助手自编的单来源先导材料，尚未合成，也没有听众辨识结果。用户已明确回复“保留草稿的角色设定和逐句归属”；三个人物设定、12 句归属现已确认。随后用户明确回复“六项均为0”，三个角色对 Mia／Chloe 的适配惩罚均已登记为 0。以上不代表新音频质量或辨识效果通过。

初版 proposed 剧本和空白人工表原样保留；另存 confirmed 剧本及本次人工确认记录，正文和非声音参数未变。

## 填写顺序

1. 角色设定与逐句归属已确认；如以后修改正文，另存新版本并重新核对。
2. 声音适配已确认：Alex、Blair、Casey 对 Mia／Chloe 六项均为 0（适合），适配评分不区分声音。
3. 固定正文与条件后合成；先质检和人工试听，再导出盲化辨识材料。

当前人工表：[human_review.fit_confirmed.json](human_review.fit_confirmed.json)；角色确认表和初版空白表均为历史记录。六项均为 0 来自用户原话，没有代填或从角色确认推断。完整适配表单独保存，可直接用于选角入口。

确认剧本：[role_script.confirmed.json](../../audiobook_output/casting_english_plan_20261016/role_script.confirmed.json)。本次仅确认人物和台词归属，不涉及声音锁定、音频质量或研究效果。

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

## v24 历史离线分配检查（未传入初始分配惩罚）

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

适配基线现已使用用户明确确认的六项零分；初版适配待填状态保留为历史记录。角色锁定仅做离线约束检验，未修改真实锁定。
首次合成前保存最终正文与声音库指纹。合成后不自动套用中文样本的 100ms 增益方案；英语接缝需要单独核验。
单句时长尚未知；不足 3 秒的辨识片段不应通过现有导出门禁。三场景属于同一自编来源，不作为独立书目切分。
实验用途为前期可行性与材料检查，正式收益验证仍需更多独立文本和听众。

当前只有两种已核验声音，无法检验多声音距离排序的收益。待更多英语声音通过核验后，可在固定材料上重新分配；也可预先登记多组不同互动结构作稳健性比较。不能仅挑出有利文本或随机种子报告。正式对照仍需人工适配表、质量合格的实际音频以及独立听众。

离线证据及各条件计划：[offline_validation.json](../../audiobook_output/casting_english_plan_20261016/offline_validation.json)。这些计划是待审材料，普通角色规划器可能重新分配重复声音；实际实验必须使用选角后的固定计划，并在请求前再次核对正文和声音，不能直接把初始 proposed 剧本当作实验条件。

## v25 当前分配与执行准备

同一已确认剧本、完整零惩罚表、两声音库和固定 seed=42，经实际 cast 入口生成以下分配；入口会计入初始配置的声音更改惩罚，因此与上节不带 initial 的 v24 离线结果不同。

| 策略 | Alex | Blair | Casey |
|---|---|---|---|
| interaction | Chloe | Mia | Chloe |
| global | Mia | Chloe | Mia |
| random | Mia | Chloe | Mia |
| fit | Mia | Mia | Mia |

全局与随机分配相同，后续合并；互动图与其共享关系相同、声音互换。适配基线保留初始 Mia，因此三个角色共享声音。这是无偏好输入下的算法输出，不是用户锁定角色音色。

四策略共 48 个逻辑单位，合并相同分配后 36 个。固定端点、模型、指令、输出参数且无失败重试／修复时，共享缓存可归并为 24 条不同请求输入、2340 个正文字符。这是执行前估算，当前仍为零请求、零新音频。没有靠更换随机种子追求结果。

**合成前尚需解决参考覆盖**：Casey 在前两场景各一句，逐章导出时缺少另一条同角色参考，第三场景又没有 Casey。不能静默仅测试 Alex／Blair 后声称三角色辨识收益。下一步需在同一条件下跨场景汇集参考，保留每份报告、音频、角色及来源核验；实际时长与质量仍须在音频存在后检查。

适配输入已修正：一旦提供表格，必须完整覆盖参与角色×全部候选声音；缺项、空值、布尔值或无效数值均报错，不将未评价的声音当成 0 分。未提供适配表时仍可使用其他三种策略。

当前搜索仍是贪心和局部交换，不承诺全局最优：本例互动图自身目标值为 1.630144，另一已有分配为 1.580144。两者互动代理值均为 1.530144，差异来自初始配置更改项；正式对照前需要处理小规模精确搜索这一实现缺口，不能把当前结果称为目标全局最优。

文件：[完整人工适配表](../../audiobook_output/casting_english_confirmed_20261016/fit_penalties.confirmed.json)、[当前离线证据](../../audiobook_output/casting_english_confirmed_20261016/offline_validation.json)。

## v26 当前状态：精确分配与跨场景参考已接通

上一节两项工程缺口已实现并通过回归。当前精确分配如下；v24、v25 的表是历史记录。

| 策略 | Alex | Blair | Casey |
|---|---|---|---|
| interaction | Mia | Chloe | Mia |
| global | Chloe | Mia | Mia |
| random | Mia | Chloe | Mia |
| fit | Mia | Mia | Mia |

互动图与固定种子 42 的随机分配相同，合并为一个条件，另有全局和适配基线两种分配。互动图目标由 1.630144 降为 1.580144，已与八种可行分配独立穷举一致；这是代理目标结果，不是听众准确率。随机方法仍为原固定种子协议，未更换种子追求差异。

下一步实际合成按三种分配共享缓存，固定端点、模型、指令、格式且无失败／修复时预估 22 条不同请求输入、2151 字符。**目前没有生成这批对白音频。**

辨识导出现在可让每个条件提供三章有序 report_paths，保留原场景与音频来源，在同一条件内选择参考。Casey 的两句可分别作为跨场景目标和参考。所有角色都必须有两条不同、至少三秒的音频，并通过逐章质量与来源核验；不满足则整包拒绝。构造材料测试已覆盖三个角色，真实对白仍须生成后检查时长、内容、接缝和一致性，人工试听后才能用于听众任务。

当前文件：[分配、固定计划与请求预检](../../audiobook_output/casting_english_exact_20261016/offline_validation.json)。人工角色与适配记录没有改变。
