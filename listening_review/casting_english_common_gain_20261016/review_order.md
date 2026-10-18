# 统一音量处理后的整章核验

本次仍使用已生成的 MiMo 音频，新增合成请求为零。三组选角共用固定协议：Mia 0 dB、Chloe -5 dB；文字、角色分配、语速、每段样本数和静音位置均保留。

请依次试听下列9章，总计约 4.2 分钟。各组都包含同一组三场景。
检查顺序：①拼接处是否完整自然；②同角色音色、语调、语速是否可接受；③有无重复、漏读或多读；④音量衔接是否舒适。正常角色换声不算漂移。

此前 F01 的降5dB接缝逐样本保留，不必再次单独回答 Bring；本次需要确认固定整章中其余部分。F03共享 Mia 的基线仍保留，声音难区分可作为选角表现记录。

可以直接在聊天回复“九章均正常”；若有问题，请写“章号＋大致秒数＋现象”。不需要再次填写旧表格。chapter_review.json 保持待核验，annotation.csv 的63行也不会由机器结果代填。

| 章号 | 选角组 | 场景 | 时长 | 试听 |
|---|---|---|---|---|
| 1 | interaction+random | 1 | 28.48秒 | [整章](audio/chapter_000001_full.wav) |
| 2 | interaction+random | 2 | 26.08秒 | [整章](audio/chapter_000002_full.wav) |
| 3 | interaction+random | 3 | 29.44秒 | [整章](audio/chapter_000003_full.wav) |
| 4 | global | 1 | 28.48秒 | [整章](audio/chapter_000004_full.wav) |
| 5 | global | 2 | 26.08秒 | [整章](audio/chapter_000005_full.wav) |
| 6 | global | 3 | 30.40秒 | [整章](audio/chapter_000006_full.wav) |
| 7 | fit | 1 | 28.48秒 | [整章](audio/chapter_000007_full.wav) |
| 8 | fit | 2 | 25.60秒 | [整章](audio/chapter_000008_full.wav) |
| 9 | fit | 3 | 30.40秒 | [整章](audio/chapter_000009_full.wav) |

每章逐句原文、角色和短接缝窗口见[完整标注说明](README.md)。网页播放器见[index.html](index.html)。

这是实验者质量核验版，包含选角组信息；尚未通过整章人工核验，不能分发为正式盲听材料。5dB来自本先导的开发反馈，不能当作跨文本、跨引擎的最优设置。机器仍存在未校准维度及待复核提示，不等于所有质量检查已通过。
