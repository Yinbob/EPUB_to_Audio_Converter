# MiMo 统一核心：使用、实现与验收

更新：2026-10-17。本文记录当前实现；早期《统一核心与质量评估实施方案》中的 MiniMax、人民币预算和拟议文件名不作为本轮实现要求。本轮只接 MiMo，约束请求次数、追加修复次数和运行时间。Qwen TTS、VoxCPM 的本地适配留在后续阶段。

最新补充（v52／v53）：用户已确认统一音量的九章材料质量正常，36题音频先导完成预审，未填写辨识答案。新增`prepare-review-queue --report quality.json --output queue.json`，保留全部诊断，把重叠范围合成按时间顺序的不重复复核路线；单词替换筛查和未校准检查不会自动通过，也不按每项分别提问。真实Flipped报告133条提示合成48个可选定位窗口，默认路线为9段不重叠范围，原始音频与状态不变。五项新增回归后全量609项、579通过、30跳过、无失败／错误；详见[当前总进度](项目进度与人工验收安排.md)。离线辨识播放器的真实浏览器验收仍未完成，JSON／CSV先导材料与该界面状态分开记录。

最新补充（v50）：用户确认统一音量版本T01／T02均完整、接缝正常，已对精确绑定的两处边界内容提示另存误报裁决。三个选角条件的九份报告通过材料导出门禁，导出36题的待人工审查先导包；回答表仍全空，不代表已完成听众实验或九章人工验收。跨场景角色配置核验现覆盖内置、描述和克隆声音，检查档案版本、实际模型／请求及克隆参考内容，不用配置一致代替听感一致。五项新增回归后，全量602项，572通过、30跳过、无失败／错误；111个既有真实音频块的身份记录核对通过，未重合成。详见[本轮记录](validation/audio_core_20261017/README.md)与[先导材料状态](/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/audiobook_output/casting_listener_pilot_20261017/material_status.json)。下方历史阶段的待审状态不自动代表最新进度。

最新补充（v49）：Flipped首章C’mon的单次朗读、发音和接缝已获用户明确确认；该处以Come on展开读法重合成，其他99块不变，候选1054.12秒。新增整块ASR误报的逐项人工裁决：精确核验实际朗读文本、正文完整与无多读，绑定报告及音频，只解除指定告警，保留原机器证据和其他未完成检查。四项新增回归后，全量597项，567通过、30跳过，无失败／错误。10个已接受修复个案按同书同章归为一组，未划分、未训练，也不估计总体修复成功率；详见[本轮记录](validation/audio_core_20261017/README.md)。下方各阶段数字和待审状态保留为历史进展。

最新补充（v47）：三处本地修复获用户“三处均正常”确认，另存指纹绑定接受记录。新增[完整朗读后的尾部重复专项检测与裁切](MiMo尾部重复检测与裁切.md)：默认导出候选，显式auto模式配合自动修复才选用严格匹配的安全裁切；短重复词和ASR歧义交给人工。本次历史音频检测及正式管线离线重放均无新TTS请求，未替换已有章节。最新全量593项，563通过、30跳过，无失败／错误；下文较早阶段数字和待确认状态保留为历史记录。

最新真实章节进展见[10月17日工程验收](validation/audio_core_20261017/README.md)：《Flipped》首章两条多读与四处长停顿的局部修复、R001参考的三条克隆小试已获本轮人工确认，已另存局部修复版。克隆角色模式已接入Provider并通过离线检验；用户随后明确授权首章67块Bryce克隆，现67次均成功，已另存17分52.88秒的新章候选。100块与99处接缝完成本地复检；R039、沿用的父亲R018疑似重复及新声音／接缝仍待人工核验，原版未覆盖，见[参考音克隆接入与验收](MiMo参考音克隆接入与验收.md)。质量评估绑定音频指纹并检查推理期间变化；最新全量580项运行、550通过、30跳过，无失败。论文所需真实缺陷数据、独立划分和听众收益仍未完成，不能将工程通过解释为研究效果成立。

## 1. 已实现的方法

| 能力 | 具体实现 | 当前可验证范围 |
|---|---|---|
| 朗读规范化 | 年份、有效中文日期、百分比、中文单位前的小数、显式用户词典；保留逐字原文映射与变换记录；另列多音字复核位置 | 歧义编号和版本号保留；提示不代表读音错误或已经核验，不自动推断读音或改写全文 |
| 跨块连续性 | 固定角色参数、句边界分块、PCM 顺序组装、只补足计划静音 | 保留首尾有效语音；检查数量、编号、顺序、产物哈希和最终编码时长；不在语音上无条件交叉淡化 |
| 拼接评估 | 波形跳变、能量、频谱、语音端点、静音与计划停顿；可加载边界分类器 | 重点检查已知拼接位置；规则与先导分类器输出疑似问题 |
| 角色一致性 | 同角色可信参考、声纹距离、音高与语速统计 | 声纹距离大于 0.35、音高偏移超过 6 半音、语速比偏离 30% 是待校准筛查规则；情绪变化需人工复核 |
| 内容检查 | 本地 SenseVoice 转写、中文读法归一、编辑距离回溯；完整左右片段联合核验 | 报告插入、删除、替换；ASR 不一致不等同确认漏读；暂定位到块／边界 |
| 局部修复 | 拼接优先；数字零静音缩短、孤立边缘脉冲淡化、小幅降速、固定朗读提示与安全二分重合成 | 候选必须改善相关质量，保留已有通过检查，不增加已知内容差异；新增内部接缝需复检 |
| 编码后复检 | 最终文件重新解码，流式核对 PCM／帧数，再按时间表做片段与接缝 ASR | WAV／无损输出可证明 PCM 未改变；有损输出依赖 ASR 筛查，不能替代人工听感验证 |
| 持久化与资源 | SQLite 请求账本、原始样本、选中指针、内容校验、独立渲染缓存 | SDK 隐藏重试关闭；失败和进行中请求占额度；已淘汰候选不自动取代选中缓存；变速复用原始音频 |
| 自动选角 | 共同探针声纹、互动图加权、人工适配惩罚、已有配置变更惩罚、用户锁定 | 可比较互动图、随机、全局分散和属性适配基线；声纹只是辨识风险代理 |

`audio_core` 包按需加载评估依赖。旧的转换入口默认保持原有行为；显式启用新核心后，普通朗读和角色朗读进入同一执行链。新核心拒绝其他引擎，首轮使用一个 worker。

小数规则只转换 0～9999 的非负数，最多四位小数，并且后面有明确的中文单位（如千克、米、摄氏度、元）；保留小数末尾的零。负数、科学计数法、千位分隔、前导零编号、无单位小数及拉丁单位暂不自动处理。版本为 `zh-reading-v3`，已有原始请求仍按实际文本复用；角色参考同时按规范化版本和词典失效。

词典示例见 [reading_dictionary.example.json](../examples/reading_dictionary.example.json)。CLI 加 `--audio_core_reading_dictionary examples/reading_dictionary.example.json`；WebUI 上传的质量设置 JSON 可添加 `"reading_dictionary":{"API":"应用程序接口"}`。词典是用户显式指定的最终朗读文本，采用原文精确匹配、同位置最长词组优先，不递归替换；拉丁词条不匹配较长单词或编号内部。限 256 项，词条至多 64 字，读法至多 256 字；禁止空串、控制字符、SSML／方括号控制标签、循环和级联替换。

替换不会改动剧本原文，记录 `confirmation=user_configured`，不表示人工已确认音频正确。朗读计划和质量报告保留词典副本；离线复评沿用该副本，ASR 比较接受明确配置的等价读法。词典可以指定缩写或专名的文字读法，不保证用不受支持的拼音／SSML 强制控制多音字；多音字仍需试听核验。

`pronunciation_review` 以 `polyphone-review-v1` 记录非穷尽的多音字复核提示，包含原文上下文、单元／章节位置和已声明的词典读法。CLI `plan`、生成报告和离线复评都会输出；WebUI 将提示列在声学问题之后，可试听对应块。提示不计为合成缺陷，不触发追加请求；无规则命中也不是读音通过。当前不自动判定正确音素，不将 ASR 同字转写视为读音金标准。

## 2. 启用转换和界面

已有环境可用 `./venv/bin/python`。CLI 示例：

```bash
./venv/bin/python main.py input.epub audiobook_output \
  --tts openai --worker_count 1 --audio_core_enabled \
  --audio_core_chunk_chars 300 --audio_core_max_requests 1000 \
  --audio_core_max_repairs 24 --audio_core_max_seconds 3600
```

显式添加 `--audio_core_repair` 才自动修复。角色模式仍使用原有 RoleScript 参数与校验；`--audio_core_casting casting.json` 可应用已审查的选角结果。修复保留角色音色、语气和正文，最多对一个块追加两次合成请求。

可另设 `--audio_core_max_repair_characters 300`，或在 WebUI 质量设置 JSON 中填 `"max_repair_characters":300`。此限额按同一 run 的追加合成正文累计：规范化后的实际字符串长度，含标点，不含风格指令；初次生成不占修复字符额度，失败与进行中请求仍占用，恢复旧缓存不追加消耗。默认 `null` 不限制，`0` 禁止追加重合成但允许本地裁剪／变速。拆分修复会先检查完整父块正文额度，避免明知不足却只发第一段；每个实际请求仍由 SQLite 事务严格检查。各章共享额度，报告的 `resource_limits` 保存实际 run 设置，旧账本未设此字段时按不限制兼容。这里衡量合成工作量，不计算费用。

比较研究策略时，可先统计同一测试集规范化正文长度，再统一指定绝对字符限额。例如基线共 1000 字符，设置 300 即允许最多追加基线的 30%；这只是实验配置示例，不是已验证的最优比例。请求次数、单块次数及运行时间限制同时生效。

对 `asr_mismatch`，追加固定的逐字完整朗读指令，不使用额外文本 LLM，不修改实际正文。原有角色指令保留。正文至少 40 字、有安全标点、每侧至少 12 字且当前 run／原始块都剩余两次修复额度时，拆成两段合成；否则只尝试整块提示修复。两段正文连接后必须严格等于原读法，不切开规范化词条；每个子请求分别占用额度，失败和进行中请求同样计数。

组合候选除父块及原有左右接缝外，还检查两个子块与新增内部接缝。内部内容检查缺失或新增接缝／内容／信号问题时拒绝选用；所有候选保留审计。首轮不对已经重分块的组合继续做本地裁剪／变速，以保持内部样本位置和检查一致；仍可在额度内重新合成。八项构造回归覆盖提示、拆分、额度、失败、拒选、恢复与离线复评，尚无人工核验的真实内容修复成功率。

每个块最多尝试两次本地动作。缩短停顿只删除片段首尾**连续且所有声道均为数字零**的样本，至少保留 20 毫秒或目标停顿的一半；低能量但非零的语音不裁切。边缘淡化只处理一个幅度大于 0.15、相邻至少 50 毫秒为数字零的孤立脉冲，普通语音、截断字音和无法确定的边界不做淡化。两种动作仅处理统一 PCM_16，不覆盖输入；不满足条件则保留原始候选，必要时在额度内重采样。安全条件不会保证停顿在语义上自然，仍需人工终评。

本地操作记录输入哈希、处理端、移除样本数／淡化长度；后续变速保留已选中的边界操作。选中后重算本块、相邻边界与同角色参考依赖，最终时间表根据处理后的实际样本数生成。拼接试听缓存同时校验两侧内容与自身 SHA，损坏时重建。

WebUI：高级设置 → **MiMo 统一质量核心**。启用检查或自动修复，可上传 [配置示例](../examples/audio_core.settings.example.json) 的修改版，以及选角文件。生成后点击“读取输出目录中的质量报告”，查看问题表、试听对应块／拼接上下文，下载 JSON。

质量状态与生成状态分别保存。`generated` 只表示成功导出；`incomplete` 表示依赖、参考、阈值或疑似问题仍待核验；确认的空音频、严重削波等可使质量状态为 `failed`。初始生成失败也有章节报告和请求账本。

## 3. 本地评估模型

第一版不要求从头训练 VAD、声纹或 ASR。本机已建立独立 `venv_audio_quality/`（Python 3.11.17），运行时位于 `venv_audio_quality_runtime/`，模型位于 `.audio_quality_models/`，总占用约 2.5 GB；三者均被 Git 忽略。原 `venv/` 保留原环境。可直接运行：

```bash
./venv_audio_quality/bin/python main_ui.py --host 127.0.0.1 --port 7862
```

高级设置可上传本次生成的 `audiobook_output/audio_core_validation_20261016/audio_core.settings.json`，使用已下载的本地模型。`main_ui.py` 仍遵守项目原有自动切换规则：若以后出现 `venv_chatterbox/`，会优先切入该环境；届时需要为实际启动 UI 的环境同步安装评估依赖。

其他机器的可选依赖在 `requirements-audio-quality.txt`，建议 Python 3.11、PyTorch／torchaudio 2.6.0，保持 Gradio 5.50.0。当前实际依赖快照在 [macOS ARM64 环境记录](validation/audio_core_20261016/requirements-macos-arm64.txt)，这是本机复现记录，不作为所有平台通用锁文件。

```bash
python -m pip install -r requirements-audio-quality.txt
python -m audiobook_generator.audio_core preflight \
  --asr-model /absolute/models/SenseVoiceSmall \
  --speaker-model /absolute/models/ecapa
```

`preflight` 不读取凭证、不调用 TTS，也不下载模型；“目录已配置”不代表真实推理已通过。各适配器延迟到需要时加载：

- SenseVoice：本地完整模型目录，复用项目 CPU 转写入口。
- ECAPA：本地 `hyperparams.yaml`、`embedding_model.ckpt`、`mean_var_norm_emb.ckpt`、`classifier.ckpt`、`label_encoder.txt`。加载时将预训练路径覆盖为本地目录；至少三秒有效语音才提取声纹。
- Silero VAD：使用安装包附带的 ONNX 模型，开启 `--audio_core_vad`。它只判断语音活动，不能判断少了哪个字。

CLI 路径参数对应 `--audio_core_asr_model`、`--audio_core_speaker_model`、`--audio_core_boundary_model`；WebUI 配置对应 `asr_model`、`speaker_model`、`boundary_model`。模型文件建议按版本分目录保存，避免同路径替换权重后沿用旧缓存。

参考：[SenseVoice 官方仓库](https://github.com/QwenAudio/SenseVoice)、[ECAPA 模型卡](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)、[ECAPA 官方加载配置](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb/blob/main/hyperparams.yaml)、[Silero VAD](https://github.com/snakers4/silero-vad)。

## 4. 离线评估与边界小模型

统一入口为 `python -m audiobook_generator.audio_core --help`，不使用被项目忽略的 `scripts/` 目录。

```bash
# 只生成朗读计划
python -m audiobook_generator.audio_core plan --text text.txt --output plan.json --voice 冰糖

# 使用已保存音频重新评估，无需重新合成
python -m audiobook_generator.audio_core evaluate \
  --manifest /path/to/quality.json --output evaluation.json \
  --asr-model /absolute/models/SenseVoiceSmall --speaker-model /absolute/models/ecapa

# 导出待人工标注的拼接位置
python -m audiobook_generator.audio_core prepare-labels \
  --report /path/to/quality.json --output boundaries.jsonl
```

每行包含 `group_id`、`split`、左右音频、特征和标签。初始 `split=unassigned`、`labels=null`，不能直接训练。人工试听后：

1. 按书籍／场景／原始音频分配 `train/dev/test`；同源变体保留同一个 `group_id`，不得跨集合。
2. 确认正常写 `labels=[]`；异常可选 `boundary_click_suspected`、`cutoff_suspected`、`overlap`、`unexpected_gap`。标签来源说明为 `origin=real_reviewed`。
3. 仅对核验正常的真实训练／开发样本设 `reviewed_normal=true`，才允许生成补充扰动。自动生成的扰动仍为 `labels=null`，先核验再训练。

```bash
python -m audiobook_generator.audio_core augment --data reviewed_normal.jsonl --output augmented.jsonl
python -m audiobook_generator.audio_core train-boundary \
  --data labelled.jsonl --output boundary_model.json --steps 1000 --seed 42
```

当前实现九维特征、四个标签的逻辑回归，CPU／NumPy 即可训练。训练集拟合参数，开发集在误报约束下选阈值，测试集只报告固定模型结果；同时输出真实测试子集与规则基线。缺少某类正负样本时不启用该类阈值；若没有任何一类在训练集和独立开发集都包含正负样本，则直接拒绝训练，不创建或覆盖输出模型。成功时，模型与命令结果均包含 `label_support`（各划分逐类正负数）和 `source_group_counts`（各划分来源组数）；这些计数不代表统计功效或真实质量验收通过。

模型输出是**未做概率校准的分数**；开发集选阈值不等于概率校准，更不等于已验证真实缺陷检出能力。先导模型只作筛查，不凭“模型没有报警”宣布整章质量通过。早期导出的两处真实边界已由用户核验，在当前四类标签中均为阴性；第一处另有衔接自然度问题，不能改记为这四类的阳性。尚未分配训练集或训练真实模型，新英语先导的 27 处边界仍待人工标注。小型 CNN／CRNN 的实现与比较以真实标注充分、特征基线确有改进空间为前提；本轮尚无这项证据，未训练神经边界网络。

ASR 转写和声纹缓存使用本地模型内容指纹，不只比较目录名。指纹包含已识别格式的权重、配置、归一化与词表文件的 SHA-256，以及 FunASR／SpeechBrain 版本；文件未变时复用进程内摘要，替换或改写后重新核验。`evaluation_models` 保留实际版本证据。同路径换权重会使旧转写、声纹及角色参考失效，并重新加载进程内模型；评估期间检测到模型变化则拒绝采用该次结果。自定义转写器未声明 `cache_identity()` 时不跨实例共用磁盘缓存。旧 `asr-v1` 转写文件保留，但不作为新版缓存命中。

八项构造回归验证上述失效、恢复与重新加载。实际已下载模型也已离线检验：一个既有自编样本 ASR-CER 为零、ECAPA 返回 192 维单位声纹，记录为 [model_identity_actual_v6.json](validation/audio_core_20261016/model_identity_actual_v6.json)。此记录不包含真实缺陷准确率或替换损坏权重的真实模型实验；模型替换分支使用构造夹具。

### 人工标注包与回填

本次可直接从 `audiobook_output/audio_core_validation_20261016/annotation/review_pack_v1/README.md` 开始，包含四段完整片段、两个接缝窗口、完整章节、原文与预期读法。人工填写 `annotation.csv`，判断值使用 `yes/no/uncertain/not_applicable`；同一角色才比较跨段一致性，正常角色切换不算漂移。短接缝窗口两端是裁切边缘，只核验中间接缝；内容完整性需结合完整片段。

后续批次可重复导出和回填，命令均只读已有音频、不调用 TTS：

```bash
python -m audiobook_generator.audio_core prepare-review \
  --reports /path/chapter1/quality.json /path/chapter2/quality.json --output new_review_pack

python -m audiobook_generator.audio_core import-review \
  --pack new_review_pack --reviews new_review_pack/annotation.csv \
  --output reviewed_boundaries.jsonl --check-only

# 人工填写完成并核验后，去掉 --check-only 才写入结果
python -m audiobook_generator.audio_core import-review \
  --pack new_review_pack --reviews new_review_pack/annotation.csv \
  --output reviewed_boundaries.jsonl
```

导出拒绝覆盖既有包；导入核验音频 SHA-256、原始边界数据、受保护的样本字段，拒绝重复／缺失编号、标签与逐项判断矛盾及覆盖既有输出。`pending/needs_review` 不转成正常标签。确认边界必须有标注人、带时区的 ISO 时间和四项明确判断；其余维度的人工意见另存审计记录，不混入边界四类训练标签。`reviewed_boundaries.jsonl.review.json` 保存完整人工表格和跳过记录。

重分块后的选中报告会同时导出父块、两个修复子块及新增内部接缝。`scope_kind=repair_part/internal_resegment` 和 `parent_chunk_id` 保留从属关系；内部接缝按父块在实际章节中的位置定位，与原始接缝使用同一来源组，不把子块当成独立来源。导出逐块核对完整 PCM 与选中片段、补静音区及内部组合，拒绝同长度内容篡改、损坏子块和过时的变换前时间表。三项构造回归覆盖内部定位、导入和拒绝分支；既有两章真实音频重新导出校验仍为六条 pending，原标注包未改动，见 [离线核验记录](validation/audio_core_20261016/annotation_and_provenance_v5.json)。

导入不会自动分配数据集，默认仍为 `unassigned`；可用 `--splits splits.json` 显式提供 `{"原始group_id":"train或dev或test"}` 的映射。同组变体不得跨集合。划分完成只证明字段齐备，不证明训练样本充分。最新用户核验为六条已填写，其中两条边界在当前四类标签中均为阴性；第一章起读生硬另记为标签集之外的衔接自然度问题。本次只做导入校验，未生成训练集或训练真实缺陷模型，见 [人工先导结果](validation/audio_core_20261016/人工先导结果_20261016.md)。

### 修复前后独立盲听先导

已有真实两章的原始编码音频与本地降速候选已导出 [盲听说明与 A/B 音频](../audiobook_output/audio_core_validation_20261016/annotation/repair_blind_review_v1/public/README.md) 和 [空白评价表](../audiobook_output/audio_core_validation_20261016/annotation/repair_blind_review_v1/public/responses.csv)。共两题、四份最终编码解码后的 PCM16 试听副本；没有额外变速、响度归一化或 TTS 调用。最新已有一名试听者、两份已核验回答，原始六条标注也已完成。两表保持独立，见 [人工先导结果](validation/audio_core_20261016/人工先导结果_20261016.md)。同一试听者参与过原始标注，本批不能视为独立盲评验收。

通用入口接受 `pairs.json`：`[{"baseline_report":"/path/before/quality.json","candidate_report":"/path/after/quality.json"}]`。各对报告必须属于同一来源章节，正文、角色、声音配置及分块一致；要求已有编码保留检查，并核对最终音频哈希。报告过旧或音频已改变时先做离线复评。每题随机 A/B；公开材料只保留原文、预期读法、匿名角色区间及各版本实际接缝位置，方法与机器结论留在独立私有答案中。

```bash
python -m audiobook_generator.audio_core prepare-repair-review \
  --pairs pairs.json --output repair_review_pack --seed 42

# 人工填写后，汇总逐维偏好；只有公开目录分发给听众
python -m audiobook_generator.audio_core score-repair-review \
  --key repair_review_pack/private_key.json \
  --responses repair_review_pack/public/responses.csv --output repair_review_scores.json
```

表格按拼接、一致性、内容、信号四维填写 `A/B/tie/uncertain/not_applicable`；核验完成须填写参与者和带时区时间。正常角色切换不算漂移，单段角色不足以比较跨段一致性时选择不适用；速度更慢不自动表示质量更好。评分校验试听材料哈希，拒绝未知试题、重复回答及不完整的已核验行；未填写行保持待核验。偏好票数不是人工确认的缺陷残留率，两章也不足以证明泛化收益。正式实验还需独立缺陷终评、更多来源、听众分组及顺序平衡；本包只提供先导材料。

五项构造回归覆盖盲化、时间表、正文／声音约束、编码与音频变化、人工表格及 CLI；不将构造回答计作真实人工数据。

### 已确认衔接生硬的受控试听

用户核验后，针对第一章约 9.28 秒处的起读生硬，已用同一最终编码音频导出 [原版与三个候选试听](../audiobook_output/audio_core_validation_20261016/annotation/transition_preview_v1/README.md)。这只是手动试验材料，未改动原始音频、既有标注或生成默认设置，不发起新 TTS 请求。

实测 RMS 低能量估计为左尾 0.36 秒、右首 0.14 秒；这不是人工确认的静音，不能据此诊断停顿不足。候选分别为追加 150 毫秒数字零、右段起读增益从 0.8 恢复到 1.0（200／400 毫秒）。增益起点按低能量规则估计，不是已验证的音素边界；它会改变短段语音幅度，不能因起始增益非零就宣称首字听感安全。

```bash
python -m audiobook_generator.audio_core preview-transition \
  --report /path/to/quality.json --boundary 'left_chunk_id|right_chunk_id' \
  --output new_transition_preview --asr-model /absolute/models/SenseVoiceSmall
```

导出拒绝覆盖，核对最终音频与报告哈希、实际样本位置，保存完整与局部试听及每项变换范围；修改范围外逐样本不变。四个真实版本的完整章节 ASR-CER 均为零，新增停顿 3600 个样本，两个音量候选样本数不变。ASR 无差异仅是内容筛查，不能替代首字清晰度或自然度试听；尚无用户对新候选的偏好结果。未传本地 ASR 时明确标记未评估，出错／文字差异不作为通过。六项构造回归验证受控范围、失败状态、来源变化与 CLI，不计作真实听感效果。

试听时先比较四个局部窗口，再用完整音频核对上下文，重点是“接得自然吗、首字清楚吗、是否变拖沓”；无需重填之前的两份表。该试验仅有一个来源接缝，不将四个版本当作四个独立样本。记录见 [transition_preview_v10.json](validation/audio_core_20261016/transition_preview_v10.json)。

## 5. 自动选角与听众辨识材料

```bash
# 此命令真实调用 MiMo；四条共同文本 × 四个声音，最多 16 次请求
python -m audiobook_generator.audio_core probe --language zh-CN --voices 冰糖 茉莉 苏打 白桦 \
  --output audiobook_output/voice_probes --max-requests 16

# 人工试听 probes.json 中各音频，确认后再标 verified=true
python -m audiobook_generator.audio_core build-bank \
  --manifest audiobook_output/voice_probes/probes.json \
  --speaker-model /absolute/models/ecapa --output voice_bank.json

python -m audiobook_generator.audio_core cast --script roles.json --bank voice_bank.json --language zh \
  --strategy interaction --output casting.json

# 需要旁白独占音色时显式开启；不会修改已有声音锁定
python -m audiobook_generator.audio_core cast --script roles.json --bank voice_bank.json --language zh \
  --strategy interaction --narrator-exclusive --output casting.json
```

声音库要求至少两条内容一致的共同探针、非静音／非严重削波、人工核验和有效声纹。`--strategy random/global/fit` 用于比较；随机种子默认 42。`fit` 需要 `--fit-penalties fit.json`，格式为角色→声音→有限非负数，值越大表示越不适配。自 v25 起，任何策略一旦提供该表，就必须完整覆盖参与角色×全部候选声音（包括已锁定角色）；缺项、未知项、空值、布尔值和无效数值报错，不能把漏填当成 0。显式全零表有效；不传表时其他三种策略仍可运行。性别、年龄等不作为未经核验的硬约束；V2 的 `voice_locked` 是硬约束，速度也保持原配置。声音不足允许复用并列出共享声音。

`--narrator-exclusive` 默认关闭；开启后，旁白的音色从其他角色候选中排除。自 v26 起，锁定和旁白独占约束后的候选组合不超过 4096 时，interaction／global／fit 枚举全部可行分配；超限才使用贪心与局部搜索。随机基线保留固定种子的原有抽样方式，先随机选可行旁白音色，再按互动度排序为角色选择尚未占用的声音，不足时复用；它不是从全部分配中均匀抽样。其他角色可在剩余声音中复用，不能占用旁白音色。旁白与其他角色已经锁定同一音色、所有候选都被其他角色锁定、或只有一个音色却同时有旁白和角色时，返回明确的约束冲突；不修改用户锁定。没有旁白的剧本标 `not_applicable`。选角结果的 `search` 记录实际方法、规模门限与最优性范围；精确最优仅针对当前声纹、适配和初始声音更改目标，不代表真实听众最优。

选角文件记录 `constraints.narrator_exclusive` 和约束状态；转换入口会再次核验实际角色分配，部分手写文件也不能绕过约束。旁白在本章没有台词时，文件中已预留的旁白音色同样受保护。应用选角保留正文及速度。八项新增构造回归覆盖四种策略、文件校验、V2 CLI、应用入口和 27 种锁定组合的可行性；这些测试不证明听众辨识收益，记录见 [casting_constraints_v7.json](validation/audio_core_20261016/casting_constraints_v7.json)。

新构建的声音库还保存每个探针的音频 SHA-256、时长、音高统计、RMS 响度、整体／发音语速，以及声纹模型内容指纹和探针清单哈希。中文语速单位是每秒归一化汉字数；英文为词／秒并另存词／分钟，发音时间采用 20 毫秒 RMS 帧和 0.003 阈值，不等同已核验的 VAD 结果；拉丁单词不计入该汉字数。建库期间模型、当前探针音频或清单变化会停止输出。`verified=true` 必须是布尔值，核验来源仍标为调用者提供的清单；程序不会替用户完成试听核验。三项构造回归验证元数据与模型／音频变化拒绝分支，这一历史阶段尚无真实共同文本声音库；当前已建中文声音库，见文末双语更新。

生成各条件的相同正文后，准备 `conditions.json`：

```json
[
  {"condition":"interaction","report_path":"/path/interaction/quality.json"},
  {"condition":"random","report_path":"/path/random/quality.json"}
]
```

```bash
python -m audiobook_generator.audio_core prepare-listening \
  --conditions conditions.json --output listening_pilot --seed 42
python -m audiobook_generator.audio_core score-listening \
  --key listening_pilot/private_answer_key.json \
  --responses collected_responses.csv --output pilot_scores.json
```

跨场景时，每个条件改用有序 `report_paths`，例如 `{"condition":"interaction","report_paths":["/path/scene1/quality.json","/path/scene2/quality.json"]}`；它与 `report_path` 二选一。各条件的场景数量、顺序及对应正文、角色必须一致，不能重复同一报告凑参考。用户应事先核对跨场景的同一角色 ID 确实指同一人物；多报告入口还检查同一条件下每个角色声音配置一致。参考仅在本条件的报告池内选择，目标和所有参考的报告、音频哈希与原来源组都记入私有答案。逐章来源组保持原值，不把多场景拼成伪造的独立书目。

v50起，声音配置一致性比较完整档案及实际请求，不再仅比较内置voice名称。描述／克隆模式须有匹配的档案ID、版本、语言、实际模型与请求；克隆还须验证本地参考内容SHA256，相同内容的不同合法路径可视为同一参考。内置模式仍兼容旧报告，但跨场景缺少档案时拒绝；同一个内置声音名下的版本、指令或实际请求改变也会阻止混入同一角色参考池。此规则用于保持实验配置固定，不是把语气变化判为音质缺陷，也不替代跨章节试听。单场景全无档案的历史格式继续兼容。

这是**提供参考声音的角色辨识先导任务**。每位角色需要至少两个不同的三秒以上片段，目标和参考不得为同一音频。材料按种子随机排序，公开文件不包含策略、真实角色 ID 或答案；只向听众分发 `public/`。须先人工审查文本是否泄露答案、音频质量是否可比；当前未自动组织或招募听众。计分输出各条件准确率和混淆计数，仅作描述统计，不提供重复测量显著性结论；无参考映射的辨识实验和真实对话连续上下文实验仍需单独设计。

v26 起，每个参与角色均须满足独立参考要求；不足时整个导出拒绝，不能跳过稀有角色后仍把材料标为完整角色任务。不同文件名、不同 chunk_id 或重复报告不能把同一音频算为两个不同片段。旧的单报告调用继续支持，材料仍需人工审核，不能用构造测试音频或空白回答证明听众收益。

导出入口现要求 MiMo 已生成报告、各块内容及信号检查通过、接缝与编码后的内容保留检查完成，且各层报告无已检出问题。整体 `incomplete` 只允许来自尚未校准的一致性／接缝检查；这仍是待人工审查的草稿，不是质量验收通过。各条件的来源组、原文、预期读法、角色与顺序必须一致。导出前逐样本核对章节 PCM、分块时间表与文件 SHA-256，并验证最终文件与报告绑定；导出失败不会发布半成品。

公开音频是报告实际选中的 PCM16 分块副本，保留该分块已采用的处理；该任务不评价完整章节的编码听感或接缝。私有答案保存来源及公开材料校验值，评分拒绝被改动的音频、题目或说明文件。输出目录必须为新路径，旧版无文件绑定的答案包须重新导出；不要覆盖已填写回答。材料无报警仍需人工核验，不能用本入口生成的构造回答代替听众实验。

## 6. 产物与恢复

```text
output/.audio_projects/<book_sha256>/
  project.sqlite
  raw/<request_key>/<sample_id>.<format>
  rendered/<content_key>.wav + .json
  asr/<audio_and_model_key>.json
  reports/<run_id>/chapter_<index>/
    reading_plan.json
    chapter.wav
    quality.json
  latest/chapter_<index>.json
```

报告保存原始与选中音频、样本时间表、原文区间、各维度证据、候选比较、停止原因、运行资源和 RTF。V2 提供章节原文区间；不含区间的 V1 剧本明确标为 unit 范围，不伪造章节定位。相同请求恢复缓存，新采样旁路缓存；失败请求与进行中请求占用本次 run 额度。章节间共享同一 run；重新启动转换会创建新 run 但复用已验证缓存，额度不被解释成跨所有历史运行的永久总限额。

`synthesis_parts` 是选中渲染的实际原始响应清单，重分块时含两个子请求及各自读法、角色参数和文件来源；兼容字段 `raw_path` 只指第一份原始响应，不能当成整段的全部来源。合并 PCM 不登记为 Provider 原始样本。`composition` 保存内部时间表、波形哈希和复检报告；位置相对父块渲染 PCM，可在界面试听子块／内部组合。SQLite `selected_renders` 保存选中组合和本地操作，重启后校验每份原始样本并恢复派生文件，不重新合成；原始样本损坏时不能继续把该组合当作有效缓存。离线复评重新运行内部检查，不复用旧判定。

`resource_summary` 继续表示本次 run 的累计实际请求；`resource_provenance` 另外保存选中样本的原始请求编号、所属 run 和已观察候选历史。成功、拒选、失败及仍在进行的请求都保留，不能把失败尝试或原始音频的逻辑生成资源抹掉。选中渲染持久化这些请求编号，重启后即使本次实际请求为零，也保留已记录的生成历史；旧缓存没有完整决策历史、样本来源事件缺失时标 `history_incomplete`，不推测未知成本。

`summarize` 的 `resources_by_run` 仍按 run 去重累计快照；新增 `recorded_generation` 按项目及请求编号对生成来源去重。两种口径可能重叠，不能相加，也不能将历史不全的记录直接用于完整策略成本比较。WebUI 摘要分别显示本次请求与已记录历史，旧报告显示历史未知。既有四份真实原始音频的来源查询保留四次成功请求、152 字符；本次查询 run 为零请求，历史策略全部候选尚未追溯，仍标 incomplete。五项回归使用构造请求验证恢复、失败保留、未知历史和汇总去重。

`final_verification` 保存最终编码文件哈希、解码 PCM 路径、帧数差、PCM 一致性与编码后 ASR 证据。帧数容差为 150 毫秒，超过时标为确认的编码完整性错误；等长重复／漏读需要内容检查，不能靠时长通过。PCM 完全相同时，`exact_pcm_equivalence` 只证明编码未改变选中的波形，不证明正文读得正确。PCM 不同时逐块及完整左右组合进行 ASR；未开启或无法加载 ASR 时保留 `incomplete`。解码采用磁盘文件、流式波形比较，不把整章音频展开到内存；单次 ASR 至多两块。

WebUI 可选择 `encoded:` 开头的范围试听编码后片段。新增确认错误会使整体质量为 `failed`，疑似对齐差异或检查缺失为 `incomplete`，不会被先前 PCM 的好结果抵消。此复检与初检可使用同一 ASR，属于工程内容保留检查，不是独立的人类质量金标准。

## 7. 验收记录与剩余工作

真实接口冒烟命令（**执行会发起 MiMo 请求**，单独运行才调用）：

```bash
python -m audiobook_generator.audio_core smoke \
  --output audiobook_output/audio_core_validation_20261016 --max-requests 4 --max-seconds 240
```

2026-10-16 已使用自编测试句执行：非流式与流式各两块，合计四次成功请求、152 个字符；两章 MP3 时长分别 19.36、13.76 秒。保留原始样本、两份章节报告和 `validation_summary.json`。最初一次沙箱网络连接失败在另一 run 的账本中计为失败请求，未被隐藏重试。

最初在原 Python 3.13 环境验证时，三个模型依赖缺失，报告标记为 `incomplete`。随后建立独立 Python 3.11 环境，下载 SenseVoiceSmall（修订 `3847d57`）与 ECAPA（修订 `0f99f2d`），并实际运行 Silero VAD 6.2.3；模型来源、完整修订和文件 SHA-256 保存在 `.audio_quality_models/provenance.json`。

实际离线复评的四块及两个拼接组合均为 ASR-CER=0；ECAPA 提取 192 维归一化声纹，同一旁白的两段距离约 0.166。VAD 支持有效发声时长与语速计算。复评结果在原项目 `reports/pretrained_reevaluation/`，保留完整音频映射，WebUI 可直接读取和试听。这只证明模型适配能运行以及这批样本的对齐结果，不能推断真实缺陷检出率。

另外在新请求额度为零时复用原始音频执行本地降速候选比较，保存 `local_repair_validation.json` 与修复音频；实际选中候选的 ASR 未新增文字差异。语速规则仍有未解决提示，因此质量状态保持 `incomplete`，不把限额内改善误报成完全合格。规则阈值与真实缺陷数据仍需核验。

最新两次本地动作检查保存在 `local_repair_validation_v2.json`：两段音频各选中两次降速，记录其余未选候选；最终编码后检查也通过。仍为零新增合成请求，未把未解决提示改为通过。

WebUI 已实际启动验证：成功刷新六份报告、读取问题表并返回拼接试听文件，记录为 `audiobook_output/audio_core_validation_20261016/ui_validation.json`；验证用临时服务已关闭。

后续新增编码后离线复评：两章最终 MP3 解码帧数差为零，四个片段、两个完整接缝组合的 ASR-CER 均为零，结果在 `reports/post_encoding_reevaluation/`。过程没有新增合成请求，整章仍为 `incomplete`。另有等长重复、截短、静音输出和真实 MP3 解码的构造回归；这些回归只验证程序分支，不作为真实缺陷检出率。

编码后试听的早期界面 API 检验见 `ui_validation_v3.json`。最新 [ui_validation_v6.json](validation/audio_core_20261016/ui_validation_v6.json) 已实际启动临时 WebUI：构造报告显示本次零请求／历史五次构造请求、两个读音提示和七个试听范围，内部接缝成功返回音频；旧真实报告也可读取和试听，历史不全时显示未知。构造音频明确不计入研究数据，检查后删除；临时服务已停止。这是实际 Gradio API 检验，不是浏览器视觉评审。完整回归为 467 项、30 项跳过、无失败，详见 [实施验收审计](validation/audio_core_20261016/实施验收审计.md)。

回归运行：

```bash
OMP_NUM_THREADS=1 KMP_USE_SHM=0 ./venv/bin/python -m unittest discover -s tests -t . -p '*_test.py' -q
```

`-t .` 避免 `tests/audiobook_generator` 遮蔽正式包；`KMP_USE_SHM=0` 用于本机沙箱共享内存限制。测试覆盖普通／角色执行、序列化、额度跨章、模型缺失、原文映射、组装错序、音频缓存损坏、选中候选恢复、左右边界修复、参考更新、声音锁定、数据泄漏和研究命令。

原环境及新评估环境均已通过完整回归；新环境在沙箱内批量派生原生子进程时出现 ffmpeg／Node SIGABRT，普通本地权限运行通过。后续正式测试结果以验收记录中的最终次数为准。

仍需完成的研究验收：人工标注真实缺陷及困难负例；建立真实训练／开发／测试集并与规则比较；核验共同文本声音探针；修复前后盲评和听众辨识实验。后续再决定神经边界模型是否值得加入。Qwen TTS／VoxCPM 的上下文续接与适配不在本轮实现中，不宣称这些实验或后端已经完成。

### 起读幅度 40% 候选复核（2026-10-16）

用户反馈前一组 400 毫秒版本略好、总体差异较小，现另存 0.4→1.0、400 毫秒候选于 `annotation/transition_preview_gain40_v1/`；40% 指波形幅度比例。此版本时长仍为 19.36 秒，局部以外 PCM 不变，完整 ASR-CER=0，零新增 TTS 请求。尚待听感核验，没有应用到默认处理。原试听包和历史清单未改动，反馈另存旁档。重现时为原 `preview-transition` 命令指定新输出目录，并追加 `--onset-gain 0.4 --ramp-ms 400`。证据见 [gain40 记录](validation/audio_core_20261016/transition_preview_gain40_v11.json)。

### 已确认的起读方案：50%→100%、100 毫秒

用户试听后确认该版本在当前候选中最好。新增预设 `onset-gain50-100ms-v1`，通过指定接缝编号启用；不自动作用于其他接缝。50% 指波形幅度，100 毫秒内线性恢复到原幅度；时间轴不变，起点仍是低能量估计。

CLI 在启用统一核心时追加：

```bash
--audio_core_transition_boundaries '1:1:narrator:chunk:1|1:2:narrator:chunk:1' \
--audio_core_transition_source_group '2c021c802f6c84424e86fee2a1679ecb30e4f9b012bd38945f187402b26806e1'
```

WebUI 在“本地模型与资源设置 JSON”中加载 [当前样本设置](../examples/audio_core.transition_gain50_100ms.settings.json)，并启用统一核心。其他项目需从实际报告复制接缝编号及该章的 `source_group_id`，同时设置 `transition_source_group`。接缝编号本身不能区分不同正文；缺少指纹时拒绝配置，编号匹配但原文指纹不符时，在任何合成前报错。未包含所配接缝的其他章节不受影响。同样正文的不同项目可能具有相同指纹，因此该字段是正文绑定，不是独立的书籍身份认证。空列表 `transition_boundaries: []` 关闭处理，不依赖自动修复开关。

该步骤在修复选择后执行，对右块及受影响接缝复检，若已有通过项退化或新增确认错误则保留原块。报告 `output_conditioning` 保存请求、输入／输出哈希、局部样本区间、复检和采用／拒绝原因；`rendered_path` 为实际输出块，`selected_rendered_path` 保留未做起读处理的选择缓存。每次恢复从该缓存重建，避免反复压低音量。重分块组合暂跳过并记录 `compound_chunk_requires_separate_review`，以保留内部子块映射。

真实 MiMo 原始缓存已离线走通该流程：两块和接缝 ASR 无差异，编码检查通过，新增请求为零；整体仍保留未完成的质量维度。工程输出采用原始 PCM，先前用户确认的试听采用原 MP3 解码副本，两者参数相同但不宣称逐字节一致。完整回归 464 项、30 项跳过、无失败。详见 [方案验收](validation/audio_core_20261016/reviewed_transition_policy_v12.json)。这是单接缝探索偏好，尚不构成跨章节的效果结论。

起读配置的正文绑定已用真实 MiMo 缓存复核：正确正文采用处理，刻意改写正文但保留编号的负向用例在 Provider 调用前被拒绝。输出 PCM 与 v12 已复检版本完全一致；本次未重新跑 ASR，不将这种等价性检查当作新的独立内容评估。完整回归为 467 项、30 项跳过、无失败，见 [来源绑定检查](validation/audio_core_20261016/source_bound_transition_v13.json)。

### 共同文本声音探针的实际先导数据（2026-10-16）

已执行 MiMo 冰糖、茉莉、苏打各四条共同短句，非流式 WAV、默认语速，新增 12 次成功请求、330 个正文字符、零修复请求。输入为项目自编探针句，不发送书籍正文。12 条原始音频、请求账本与运行计划保存在 `audiobook_output/mimo_voice_probe_pilot_20261016/`。

本地 SenseVoice 内容筛查 12 条均无文字差异，信号阈值检查未提示静音或削波；ECAPA 均提取 192 维单位声纹。未据此判定人工听感合格：原始清单的 `verified` 全为 false，`human_review.json` 中 12 条样本和三种声音的跨文本一致性仍待人工确认。已实际验证 `build-bank` 拒绝这份未核验清单，不生成已验证声音库。声纹距离只保留为机器诊断，没有开展独立听众辨识实验。

下一步请打开 [共同探针试听清单](../audiobook_output/mimo_voice_probe_pilot_20261016/README.md)，按同文本横向比较、同声音纵向复核；可直接在对话中按样本编号说明问题。既有六行章节标注及两道 A/B 表无需重填。详见 [本轮证据](validation/audio_core_20261016/common_voice_probe_v14.json)。

### 中英双语、英语优先（2026-10-16）

用户已确认中文 12 条共同探针的内容、信号及三种声音跨文本一致性无问题，登记在 `audiobook_output/mimo_voice_probe_pilot_20261016/human_review.json`。原始清单不改，派生核验清单 `probes.reviewed.zh.json` 绑定原清单、复核文件及音频指纹；用本地 ECAPA 实际建成 `voice_bank.zh.json`（3 声音 × 4 探针，192 维），仅标记 zh。上节 v14 的“待核验”是生成时状态。

统一核心现在为中文／英文分别计量：英文 WER、中文 CER；英文保留词界、缩略词撇号和否定词，大小写和普通句读不计差异。数字和口语读法、缩写和完整形式尚不自动做无条件等价；例如 20/twenty 可用显式朗读词典配置。混合文本标为 mixed_token_error_rate，不冒称 WER/CER。英文不转换为中文数字读法；中文明确上下文的日期、百分数与单位小数继续处理。

分块新增英文句号和空白回退，保护单词、小数与常用缩写；为完整单词或词典读法可超出目标字符长度。英文修复提示采用英语并保留角色参数。英文语速上限使用 `--audio_core_max_english_wpm 300`（也可在质量设置 JSON 里写 `"max_english_wpm":300`），默认 300 词／分钟是未标定的保守筛查规则，绝非最佳朗读速度；实际语速按预期读法词数和音频时长估算，内容有误时需一起复核。报告同时保存总体 WPM、有效语音词／秒与单位，不与中文字／秒直接比较；混读暂不判断单语言语速。

```bash
# 英语作为研究工具默认目标；以下为真实请求示例，已有先导无需重跑
python -m audiobook_generator.audio_core probe --language en-US \
  --voices Mia Chloe Milo --prompt-count 2 --max-requests 6 \
  --output audiobook_output/english_voice_probes

# 正文转换沿用 main.py 的语言参数，英语为默认语言
python main.py english.epub output_en --tts openai --language en-US --audio_core_enabled \
  --audio_core_asr_model /absolute/models/SenseVoiceSmall \
  --audio_core_speaker_model /absolute/models/ecapa

# 选角仅接受在目标语言下已核验的声音库
python -m audiobook_generator.audio_core cast --script english_roles.json \
  --bank voice_bank.en.json --language en --strategy interaction --output casting.en.json
```

新声音库保存 `languages`，选角保存 `verified_languages`；生产应用时核对正文实际语言，拒绝跨语言套用或未声明语言的旧选角文件。老库须补做对应语言核验并重建。中英混读当前可合成和检查内容，但暂不自动选角，需人工锁定声音。

实际英语先导：Mia、Chloe、Milo 各两条，共 6 次成功 MiMo 请求、519 个正文字符、49.44 秒。E01～E05 自动 WER=0；E06（Milo 第二条）的原始及最终编码转写均出现句尾额外内容，保留疑似状态，未自动修复、未建“已核验英文库”。普通旁白及双角色两章复用原始样本组装为 MP3，均在零请求额度下完成，最终编码结构检查通过；内容差异原样保留。试听清单位于 `audiobook_output/mimo_english_probe_pilot_20261016/README.md`。

这些是功能与先导证据，不能证明跨语言质量、英语阈值或听众辨识收益；英文探针人工核验、真实边界阳性、独立数据划分及听众实验仍待完成。

本轮完整回归：478 项、30 项跳过、无失败，13.385 秒；新增 11 项双语回归。详见 [v15 工程记录](validation/audio_core_20261016/bilingual_english_priority_v15.json)。

### 英文数字与日期的有限等价核验（v17）

此更新替代 v15 中“20/twenty 只能用词典”的状态说明：内容比较现自动接受含义明确的整数、小数、百分数、序数及有效英文月份日期读法；例如 `3.5%` 与 `three point five percent`、`October 16, 2026` 与 `October sixteenth twenty twenty six`。英语发送正文保持原样，报告保留规范化版本、转换事件与复核原因。语速计数按规范化后的参考词数估算，不代表已有逐词时间戳。

编号、版本、前导零、单独四位年份、斜线日期、非法日期和缩写不自动展开；数字范围、精度和年份有边界，普通基数词英式 and 等尚未覆盖形式仍可能需显式词典。比较事件坐标是 NFKC／词典处理后的文本坐标，原文位置继续查分块来源映射。混读不使用英文数字等价规则。

九项新增回归包含真实管线的假引擎检查：等价读法不重合成，错数仍提示并受请求上限约束。完整回归 487 项、30 项跳过、无失败；原有 18 条中英音频离线重查，17 条文字无差异，E06 疑似额外朗读仍待人工。没有新增 MiMo 请求或数字专项真实样本，不宣称检测或修复收益已验证。[v17 工程记录](validation/audio_core_20261016/english_reading_equivalence_v17.json)。

英文试听访问已修正。可打开 [简短路径试听清单](../listening_review/english_20261016/README.md) 或同目录 `index.html`，其中六条音频及两章均为原始文件的相同副本；也可取 [完整试听 ZIP](../listening_review/english_20261016.zip)。E06 和其他英文样本尚待人工确认，未建已验证英文声音库。

## E06 真实修复、英语声音库与语速判断更新（v19）

实际执行了受限内容修复：首个 run 在沙箱中无法解析 MiMo，账本记一次 APIConnectionError；沙箱外仅 DNS／HTTPS 连通性检查通过后，单独 run 再执行一次受限请求，成功返回 86 字符对应的 12.96 秒 WAV。两次尝试均保留，只有一次获得音频，SDK 隐藏重试关闭。

机器复核仍提示正文之后重复首句，8 个额外词，WER 从 0.9375 降为 0.5。管线按相对改善保留该候选，但内容仍为 incomplete，不能算修复成功，不能替换人工失败原件或进入声音库。最终 WAV 与选中 PCM 一致，因此编码保留检查通过；该 passed 仅表示编码未损伤候选，绝非正文正确。候选 E06R 已导出至简短路径试听目录，等待人工判断。

本次真实案例暴露了参考词数估速的混淆：多读时，实际词数比原文多，估算会偏低。现保留数值和原因，但已检出内容差异时不触发 too_fast／rate_drift；参考块已知内容错误时也不用于语速漂移比较。声纹／音高检查仍保留，内容差异继续触发复核／受限内容修复。ASR 关闭或不可用时，沿用显式标记的未验证语速启发式，不自动判内容通过。策略版本纳入角色参考和选中渲染缓存上下文。原 E06 与新候选实际离线复核均保留 asr_mismatch，移除受混淆的 rate_drift，音频本身未因本改动改变。

已使用 E01～E04 构建仅英语的 Mia／Chloe 声音库，每声音两条共同文本、192 维单位向量；人工复核、音频 SHA 和声纹模型版本已核对。Milo 因第二条未合格而暂不纳入。建库零新增 TTS 请求；没有将声纹代理结果当作听众辨识收益。

新增五项回归，覆盖多读／漏读／替换、正常内容仍能检出语速异常、错误参考、关闭 ASR 的显式状态及修复管线不对错读音频降速。完整回归 492 项，30 项跳过，无失败，13.917 秒。[v19 工程记录](validation/audio_core_20261016/english_content_repair_and_rate_gate_v19.json)。英文候选人工核验、真实边界阳性与独立划分、听众辨识实验仍未完成。

当前英语声音库：`audiobook_output/mimo_english_probe_pilot_20261016/voice_bank.en.mia_chloe.json`。仅两种声音；如需两个角色加独占旁白，容量不足时应明确报冲突，不能悄悄复用。

## E06R 重复确认、按句试验与尾部候选（v20）

用户确认 E06R 两句正文完整，但之后又重复第一句。已登记内容失败，信号与 E05 音色比较此次未回答，保留未知；不把未回答的项代填通过。原音频和人工回填前备份保留。

按既有安全二分修复方案，保持 Milo 和原文，两次新增 MiMo 请求合计 86 字符，分别合成两句。第一句单独输出仍被 ASR 检出重复，WER=1；第二句 WER=0。新组合全文 WER=0.5，内部内容检查未通过，管线拒绝采用，没有将较低 WER 解释为修复成功。此结果支持继续保留内容复核，不能证明“缩短输入就解决问题”，也不足以归因整个 Milo 音色或某个服务端参数。

另为已人工确认的 E06R 制作源指纹绑定的零请求人工试听 E06T：仅在 7.90～9.58 秒低能量区的中点 8.74 秒截断，中心 400ms 不在 Silero 语音区内。保留两句全文与移除重复句的 ASR 均无差异，保留 PCM 不变，保留和移除部分可逐样本还原原音频。没有改幅度、速度或制造新接缝。低能量／VAD 不是音素级保证；本候选仅待人工核对句尾完整与声音一致，不接自动修复、不进已核验声音库，也不当作独立效果证据。

本轮未改合成／评估源代码，不重复无关完整测试；实际检验覆盖原文区间、两次请求账本、内部组合拒绝、模型转写、PCM 和音频／人工记录指纹。最近完整源码回归为 v19 的 492 项、30 项跳过、无失败。英语库仍为 Mia／Chloe 两声音，真实边界阳性、独立划分和听众辨识试验仍未完成。[v20 记录](validation/audio_core_20261016/e06_repetition_and_tail_preview_v20.json)。


## 英文数字真实先导与跨段比较修正（v22）

用 MiMo 的 Mia、Chloe 各生成相同两句自编英文，覆盖 October 16, 2026、3.5%、21st、24、3rd、18。实际 4 次成功请求、262 字符，无追加修复；原文中的英文数字仍原样发送，分块输出未变速或渐变。两章为 15.20 秒与 15.04 秒，共享相同正文来源组，不当作两个独立来源。

真实运行发现比较规则缺陷：英文相邻单元在句末标点后缺少空白，`3.5%.The` 使百分数规则因疑似版本上下文而未触发，四条单块均无文字差异，两处联合核验却出现误报警。现仅对联合核验参考补充英文词界，保留已有空白、连字符及中文连接方式；不改写单块正文，不修改音频。比较版本升级至 bilingual-reading-v6，并在重新评估元数据中记录；旧生成报告原样保留。

离线复评同批真实音频，四条单块与两处联合核验 WER 均为零，最终编码 PCM 保留检查通过；一致性／拼接阈值未校准，整体仍为 incomplete。新增三项回归覆盖真实触发形式、引号／缩写／中文／连字符及真实错读、百分号遗漏、否定词漏读和重复仍被提示。完整回归 502 项、30 项跳过、无失败。复评零新增 TTS 请求。

试听与待标注材料在 `listening_review/english_numbers_20261016/`，先看 `numeric_reading_notes.md` 或 `index.html`；CSV 六行均为 pending。先听完整两句检查拼接和同声音一致性，再核对数字与句首句尾。自动 WER=0 不是人工听感通过；本批未加入已核验声音库，未训练边界模型。E06T 仍待另行确认，独立听众实验及真实缺陷训练数据仍未完成。证据见 [v22 记录](validation/audio_core_20261016/english_numeric_pilot_and_join_fix_v22.json)。


## 复评报告的来源与试听文件复用（v23）

编码保留报告新增 `reference_pcm_path`，与已有 `reference_pcm_sha256` 一起指向原章节 PCM。`evaluate`、`prepare-review` 和角色辨识材料导出共用来源解析；复评前核对实际章节、分块哈希和逐样本时间表。报告可另存到项目外目录，再用于下一次复评或标注导出；原音频仍须存在且保持内容一致，不代表整本项目可以不保留音频而迁移。明确声明的来源缺失、相对路径或哈希不符时拒绝操作，不悄悄改用邻近文件。

历史报告没有该路径字段时，可根据已记录的分块项目、run 与章节恢复旧路径；已有 SHA 仍须匹配，后续仍完整核对 PCM 时间表。重新评估会补齐新来源字段，原报告不改写。旧标注包与人工回答无需重填。

不同输出报告的接缝试听和编码解码副本按来源、输出位置、评估设置及比较版本隔离保存，避免同一目录下的第二次复评覆盖第一份报告的试听内容。真实英文两章验证了旧报告复用、二次复评、标注导出和相邻任务文件互不覆盖；新增 TTS 请求为零。五项新增回归通过，完整回归 507 项、30 项跳过、无失败。人工核验状态保持不变，记录见 [v23 证据](validation/audio_core_20261016/reevaluation_source_binding_v23.json)。

## 英语选角材料待审（v24）

新增 [三角色英语对白草稿](../listening_review/casting_english_plan_20261016/README.md)：三场景、12 句，逐句归属保留 proposed，人工确认和 Mia／Chloe 适配表为空。先核对正文和角色，再评声音适配；目前没有合成音频或开展听众辨识。

离线应用互动图、全局与固定种子 42 的随机分配，核对源区间、正文及非声音参数保持一致、已核验声音范围和硬锁定约束。两种声音分配三个角色时必然共享；本例互动图与随机结果相同，全局仅互换声音，共享关系相同、公共声纹代理值也相同，未显示策略优势。不能用代理值声称辨识率提高，也不因结果相同而更换种子追求有利差异。正式实验仍需人工适配表、质量合格的音频、更多独立文本和听众。

源正文和选角后的固定计划在 `audiobook_output/casting_english_plan_20261016/`，并保存来源、声音库指纹和离线检验记录。普通角色规划器可能重分配重复音色，不能直接将初始剧本当作实验条件；请求前须核对实际应用选角后的计划。本轮未改生产代码、无新 TTS 请求，最近完整回归仍为 v23 的 507 项、30 项跳过、无失败。[v24 证据](validation/audio_core_20261016/casting_english_materials_v24.json)。

后续用户已明确保留三个人物设定及 12 句归属，确认版另存为 `role_script.confirmed.json`，初版及正文保留。当前人工表为 `human_review.confirmed_roles.json`，六项声音适配尚未填写；本次确认不代表音频质量或听众辨识通过。[人工确认记录](validation/audio_core_20261016/casting_english_user_confirmation_v24.json)。

## 完整声音适配表与真实入口预检（v25）

用户随后明确回复“六项均为0”，已另存 `listening_review/casting_english_plan_20261016/human_review.fit_confirmed.json`，表示 Mia／Chloe 对三个角色都适合，适配评分不区分声音。直接可用的完整表在 `audiobook_output/casting_english_confirmed_20261016/fit_penalties.confirmed.json`。没有据此确认新音频质量、选择角色锁定或认定辨识收益。

修复适配缺项默认零的问题：原程序会优先选未评价的声音，构造反例已实际复现。现完整覆盖校验在优化与写文件之前执行；结果记录 `fit_penalty_policy=complete-matrix-v1`、启用状态及完整分数。四项新增测试覆盖缺项、空值、非数值、未知项、明确零分、硬锁和 CLI 报错不创建／覆盖输出。完整回归 511 项、30 项跳过、无失败，15.387 秒。

实际复用已确认英语剧本及 Mia／Chloe 库，通过 cast 入口生成四种分配，正文、速度、指令与停顿保持，初始声音更改项同样启用。全局与随机分配相同；互动图与其共享关系相同而声音互换；适配基线因无偏好而保留三角色初始 Mia。四策略 48 个逻辑单位，合并分配后 36 个；固定端点与模型等参数、无失败或修复时，共享缓存规划为 24 条不同输入、2340 字符，尚未实际合成。规划签名不冒充包含端点及适配器附加指令的实际 Provider 指纹。

尚需在合成前处理两个实现缺口：小规模精确搜索，以及跨场景参考池。当前贪心／局部搜索在初始更改惩罚下可停于较差目标，不能声称全局最优；当前逐章导出中 Casey 每场景仅一句，无法成为同时具有独立同角色参考的目标，不能静默只测试高频角色后泛化到三个角色。前者需要小规模穷举或剪枝与现有硬约束结合；后者需汇集同一条件的场景报告并保留文本、角色与音频指纹。实际时长、质量与听众任务仍未验证。本轮零新增 TTS，请见 [v25 证据](validation/audio_core_20261016/casting_complete_fit_v25.json)。

## 精确选角与跨场景辨识参考（v26）

上节两项工程缺口现已实现。小规模枚举覆盖锁定及旁白独占后的所有可行组合，超限回退并明确不保证最优；随机方法保持原协议。三项新增测试用独立穷举核对目标和可行组合数，覆盖初始声音、完整适配表、旁白与锁定，以及门限前后行为。当前已确认英语材料的八种分配实际复核通过，互动图目标从 1.630143880644932 降到 1.580143880644932。旧分配和人工记录不修改；新输出在 `audiobook_output/casting_english_exact_20261016/`。

跨场景参考池支持有序 report_paths，逐报告沿用质量、PCM、编码与文件指纹核验，并逐场景核对条件对应关系；同一条件角色声音一致，任何角色没有两条不同且至少三秒的音频就拒绝导出。私有答案记录目标及每条参考的来源报告、来源组和块 ID。五项新增测试覆盖稀有角色的跨场景目标／参考、同块 ID 在不同章节的区分、公开信息隔离、缺少角色参考、重复音频、顺序／声音／质量错误及 CLI 入口。构造两场景、三角色、两条件共 16 个试题，Casey 在两个条件均覆盖；空白回答评分结果为空，没有真实听众结果。

完整回归 519 项、30 项跳过、无失败，15.458 秒。实际英语分配中互动图与随机相同，合并条件；与全局、适配基线共三种分配。固定请求配置且无失败／修复时，计划归并为 22 条输入、2151 字符；当前仍为零新增 TTS。正文、速度、停顿、指令、声音库和人工适配保持。场景汇集后的单位数为 Alex 5、Blair 5、Casey 2；实际音频是否达到三秒、质量门禁和独立参考要求仍须在生成后检验，不把单位数当作音频已合格。[v26 证据](validation/audio_core_20261016/casting_exact_scene_v26.json)。


## 英语选角先导实际音频与质量核验（v27）

执行前锁定 v26 的三种不同声音分配、用户确认的正文／归属、六项零适配和声音库。先一次性生成共享原始请求池，再以新增请求上限零运行组装和本地 ASR／声纹／VAD 评估，并禁止网络合成入口兜底。MiMo 实际成功 22 次、2151 字符，零失败重试、零修复请求；保留 22 条原始 WAV，总时长 154.56 秒，最短 5.76 秒。三分配×三场景共九章，组装阶段新增请求零。未使用英文增益、裁切或变速。

36 个逻辑分块的单段内容 WER=0、信号检查通过，所有分块渲染 PCM 与原始音频一致。九章最终 WAV 与参考 PCM 一致；27 处两句联合试听重建后逐样本一致，未发现本地遗漏。整体仍为 incomplete：第 3、6、9 章第一接缝的联合转写均把 Bring 记为 B（WER=0.025），单段未提示差异；三份音频和 ASR 缓存键不同，排除本轮缓存串用。第 2、8 章第四段复用同一条 Mia／Alex 音频，语速比参考约 1.335，被两次提示。不能将这些提示直接当作人工确认缺陷，也不能用 PCM 保留或单段 WER=0 直接认定发音及听感正确。

导出 63 行待标注（36 分块、27 接缝）和 72 份基础试听文件，并另列七条重点试听及九章完整播放页；所有人工结果保持空白／pending，复制文件与来源指纹一致，页面相对链接及 WAV 元数据通过核对。质量门禁实际拒绝辨识材料，未发布盲化包。实验者质检包含条件信息，不能当作听众材料。原始正文、已有声音库、角色／适配人工记录及质量报告指纹保持；README 更新前单独备份。

本轮无产品源码变更，不重复完整回归；最近一次完整回归为 v26 的 519 项、30 项跳过、无失败。实际音频／缓存／来源重建与链接核验另存为 v27 证据。本批属于一个自编来源，未产生听众结果、真实边界阳性标注或独立来源划分；E06T 与英文数字人工核验继续待回复。

试听入口：[优先核验清单](../listening_review/casting_english_audio_20261016/focused_review.md)、[播放器](../listening_review/casting_english_audio_20261016/index.html)。[v27 证据](validation/audio_core_20261016/casting_pilot_v27.json)。


## 边界模型训练数据门禁（v28）

构造全阴性对照实际复现：原入口可拟合并输出一个四类阈值全部未就绪的模型。这不是已标注真实数据的训练，也不说明真实检测效果。现提前检查每类在 train／dev 是否分别具备正负样本；没有任何可用类别则拒绝，不执行拟合、不创建或覆盖模型。保留部分类别可用时的先导流程，缺少支持的类别仍不启用阈值。成功结果和模型增加 label_support 逐划分、逐类别正负数，以及 source_group_counts；计数不等于统计功效、概率校准或质量验收。

新增四项测试，覆盖全阴性／全阳性拒绝、训练与开发可用类别不相交、测试标签不影响模型参数及开发阈值、CLI 无产物／不覆盖旧模型／不调用网络；扩展已有部分标签测试检查计数。定向 12 项通过，完整回归 523 项、30 项跳过、无失败，15.264 秒。旧模型预测格式保持兼容；输出分数继续为 uncalibrated_scores，不升级成自动通过。

本轮零 TTS 请求、零真实训练。v27 已绑定的 26 份音频清单、报告、试听和待填人工文件指纹核对保持；此前两处人工边界在当前四类标签中均为阴性，不因本轮构造控制变成阳性。新的英语人工核验、真实边界阳性、独立来源划分及听众实验仍未完成。真实数据不足时继续规则基线，不强行训练神经网络。

[v28 证据](validation/audio_core_20261016/boundary_training_guard_v28.json)。


## 英语人工反馈与局部响度试听（v29）

直接用户反馈：F01 后段更响，F02 无问题，F03 声音相似难辨认；F06／F07 差异可接受、无明显异常。按原音频指纹保存局部人工记录，空白记录先备份。F02 的 Bring 完整和该接缝可接受、F06 的同源音频（用于第2／8章）比较可接受；F01／F03 的 Bring 完整性及其他整章仍未知，不能代填通过。原63行CSV未改，不能把音量差或共享声音推断成四类边界缺陷阳性。

实际报告核对 F03 的 Alex／Blair 都是 Mia，是全零适配表下保留初始声音的基线。该现象支持记录本先导的辨识困难，但不是两个不同声音距离的验证，也不是独立听众收益。原分配和六项适配不改；正式选角比较须对各条件采用同一响度协议。

增加 preview-loudness 零请求入口：校验报告／最终PCM／各选中块，测量完整左右句的输入响度，只对更响右句恒定衰减，默认最多6 dB，输出来源绑定的全章及两句对照；不淡入、不变速、不裁切、不覆盖原件，不进入自动修复。ASR缺失／失败／差异保留状态，测量无效或来源变化时不发布；既有输出拒绝覆盖。

实际 F01 为 Mia→Chloe，积分测量 -22.44／-17.44 LUFS；右句降低5 dB（线性0.562）后测量差0.00 LU。全章706560样本、24000Hz保持，右句之外逐样本不变，候选严格等于声明的恒定增益与PCM16量化，没有削波；原两句PCM等于既有F01。原ASR仍将Bring记为B，处理候选无文字差异；不能据此认证原音频断音或候选听感通过。候选仍待人工偏好，未替换原报告或正式辨识材料。

四项新增构造回归覆盖操作范围、上下文／静音保留、增益限额、失败原子性、来源篡改、模型变化、ASR差异和CLI零网络；定向4项通过，完整527项、30项跳过、无失败。真实运行零TTS请求，原机器报告、声音库和音频保持。

[v29 证据](validation/audio_core_20261016/casting_feedback_loudness_v29.json)。


## 英语接受结果与来源绑定人工裁决（v30）

用户明确确认“新版本更自然，音量差可接受”及“F01、F03 的 Bring 都完整”。结合此前 F02 无问题，三处 Bring→B 联合转写提示均在本样本内记为人工确认误报；不是三个独立来源的准确率估计。同一F06在第2／8章的语速提示沿用人工可接受结论，不能算两个独立样本。F01降5dB的接受记录另存并绑定生成清单、原音频和候选SHA，初始manifest不改；全章文件仅供上下文，不宣称其他片段已验收，不自动对其他来源启用该增益。

新增 adjudicate-quality 入口：逐问题指纹绑定原报告和音频，只支持本次所需的边界内容误报及语速可接受变化；保留修改前check的machine_evidence，不修改原报告／波形，不消除其他问题或严重错误。人工新增已知问题可继续阻止使用。派生报告按原PCM补齐绝对来源，另存位置不丢旧报告上下文。辨识来源门禁重建裁决结果并比对，原报告／人工记录变化或派生内容被改写时拒绝；导出中途变化也拒绝且不发布部分包。裁决依据仅入私有来源记录，公开盲化材料不含这些身份或方法。

实际另存五份报告：三处内容提示、同一音频两处语速提示。第2／6／8／9章可作待整章人工核验的材料草稿，整体仍为incomplete；第3章原件另记human_loudness_mismatch继续拦截。接受替代预览不能让未处理原件通过，整组辨识材料仍被拒绝、无半成品、无听众结果。原九章报告和音频指纹保持，零TTS请求、零真实训练、CSV未代填。

新增五项测试，覆盖裁决精确性、原机器证据保留、重定位PCM、来源／裁决篡改、错误位置和重复／无效裁决、已知问题继续阻断、CLI拒绝覆盖、导出期间人工依据变化、私有依据和公开盲化隔离。初次定向检验发现旧夹具另存目录后找不到PCM，已在派生报告显式绑定来源；另移除测试类直接导入造成的重复发现，初始日志保留。定向五项通过，完整532项、30项跳过、无失败，15.327秒。

后续须统一各选角条件的响度处理协议并核验固定全章版本；真实边界阳性／独立来源及听众辨识实验仍未完成。局部质量接受不等于论文方法效果通过。

[v30 证据](validation/audio_core_20261016/quality_adjudication_v30.json)。


## 三组选角统一音量处理与离线复评（v31）

在F01新版本接受后，制作统一条件副本：所有选角组对Mia用0dB、Chloe用-5dB，完整语句恒定增益；固定正文、分配、语速、样本位置与原静音时间表。参数来源是本先导开发反馈，不视为独立验证或普遍最优值，未全局启用。入口prepare-casting-gain要求完整显式声音增益表，拒绝放大、遗漏、重复来源、不同正文场景、角色内换声、人工裁决迁移、复合分块或重复处理；来源变动时不发布半成品。

已离线复评9章、36段、27处完整两句接缝：36段ASR无文字差异、信号检查通过；9章最终编码逐样本保留；27处复评窗口与最终章节实际接缝逐样本一致。F01已接受接缝在新第3章中逐样本保留。保留原始报告和音频，新增TTS请求为零、原生成仍22次。新版本未自动继承人工接受结论，整体质量仍incomplete，仍有待人工复核的提示，未发布辨识听众包。另存63行待标注及九章顺序试听页，尚无完整章节人工验收或听众成绩。

新增4项检验，覆盖完整统一协议、精确增益及静音保留、输入条件混杂与非法参数拒绝、来源中途变化原子失败、CLI离线与未复评门禁、复评状态更新且不捏造内容通过。首轮发现复评阶段状态更新放错入口，已修正并补充实际复评检验，原始失败日志保留。完整536项、30项跳过、无失败。

[v31证据](validation/audio_core_20261016/casting_common_gain_v31.json)。


## 角色音色设计后续接入

2026-10-16 已核实 MiMo 系列另有 VoiceDesign 与 VoiceClone；现有先导仅使用预置声音模型。后续角色声音卡、模型请求分支、稳定性核验和互动约束设计见 [MiMo角色音色设计接入方案](MiMo角色音色设计接入方案.md)。该扩展仍为方案，尚未接入或生成新音频；既有九章保留作预置声音对照。


## 长篇混合角色声音的具体规格（待实施）

用户明确采用对白量较大的角色优先内置声音、低频角色固定描述声音的方向。已将全书统计、旁白及锁定容量、角色级模型路由、跨章一致性、6次设计请求先导及逐阶段验收整理至[混合角色声音方案](MiMo角色音色设计接入方案.md)。仅更新实施规格，尚未生成新音频，现有预置声音先导不算混合分配实验。


## 2026-10-17 混合选角接入

全书对白统计、内置容量分配、LLM固定声音卡和按角色路由 VoiceDesign 已接入。六条英语先导已由用户核验内容完整、同角色一致及两角色可区分；三个新混合场景的响度匹配版随后获得用户确认“三个章节均无上述问题”，通过本轮指定检查，原机器告警保留。描述角色固定参考需要明确人工确认，不自动把首条生成认定为身份锚点。网页质量JSON现支持 `role_references`，正式转换入口两章混合路由及固定参考已通过离线集成检验。回归558项，528通过、30跳过，无失败；这不是多书籍或独立听众效果验证。命令和核验流程见 [MiMo混合选角使用与验收](MiMo混合选角使用与验收.md)。
