# 英语对白先导：优先核验清单

本次 MiMo 实际成功 22 次、2151 字符，保留 22 条原始响应；没有自动重试或质量修复。三种不同分配×三场景共九章，组装／质检新增请求为零。
已有局部人工反馈；最新状态见[本次反馈与响度对照](feedback_and_next_review.md)。原清单其余范围仍待核验。先按拼接、同角色一致性、内容、信号的顺序检查；正常换人时的声音改变不算一致性故障。

## 第一步：听第三场景第一处接缝

左句结束为 “…too faint to read in this light.”，右句应从 “Bring it closer to the window…” 开始。请检查 Bring 是否完整，是否有断音、漏音或生硬衔接。
三个联合转写均将 Bring 记为 B，但单段检查无文字差异。三个接缝音频、ASR 缓存键不同，均逐样本包含完整的左右原始块，未发生本地裁切或缓存串用。仍不能仅凭这些工程证据认定听感正常。

- [F01 · 第 3 章完整两句接缝](focus/F01_scene3_join.wav)
- [F02 · 第 6 章完整两句接缝](focus/F02_scene3_join.wav)
- [F03 · 第 9 章完整两句接缝](focus/F03_scene3_join.wav)

单段对照：[F04 · Chloe 朗读 Bring](focus/F04_Bring_Chloe.wav)、[F05 · Mia 朗读 Bring](focus/F05_Bring_Mia.wav)。

## 第二步：比较 Alex 的语速

第 2 与第 8 章第四段使用同一份音频，只需试听一次。请与同角色参考比较，判断是否明显过快、音色或语调是否异常；正常的表达变化可以说明“可接受”。
- [F06 · 待核验句：I can hold the bag…](focus/F06_Alex_target.wav)
- [F07 · 同角色参考](focus/F07_Alex_reference.wav)

## 第三步：完整章节与其余标注

优先两类问题核验后，再听下列九章确认其余接缝和角色内一致性。annotation.csv 共 63 行（36 段、27 处接缝）全部 pending；机器提示和人工判断分别保存，不代填通过。
这是实验者质检包，含条件信息；不是可直接分发的盲化听众材料。听众包已被现有质量门禁拒绝，尚未发布。

| 章节 | 条件 | 原场景 | 全章试听 |
|---|---|---|---|
| 1 | interaction+random | 1 | [试听](audio/chapter_000001_full.wav) |
| 2 | interaction+random | 2 | [试听](audio/chapter_000002_full.wav) |
| 3 | interaction+random | 3 | [试听](audio/chapter_000003_full.wav) |
| 4 | global | 1 | [试听](audio/chapter_000004_full.wav) |
| 5 | global | 2 | [试听](audio/chapter_000005_full.wav) |
| 6 | global | 3 | [试听](audio/chapter_000006_full.wav) |
| 7 | fit | 1 | [试听](audio/chapter_000007_full.wav) |
| 8 | fit | 2 | [试听](audio/chapter_000008_full.wav) |
| 9 | fit | 3 | [试听](audio/chapter_000009_full.wav) |

可在聊天回复 F01／F02／F03 的 Bring 与接缝是否正常，以及 F06 相对 F07 是否有不可接受的语速差异；需要修改的具体词和秒数请一并说明。
原先 E06T 和英文数字样本属于另外两组待核验材料，本清单不替它们填写结果。
