# MiMo 混合选角：使用与本轮验收

2026-10-17。已接入研究命令行和现有角色合成链。首轮仅使用 MiMo 内置声音及 VoiceDesign；不涉及 MiniMax，也不计算金额。六条英语先导已由用户核验；三个混合场景的音量匹配版也已通过本轮提问所列检查。中文有离线计数及参数测试，中文新描述声音尚未在线验收。

## 已实现的行为

全书角色按预计对白时长排序，旁白单独处理。同章连续同角色的文字先合并计数，避免切片数量改变排名；记录真实章节有序位置及缺席章节数。英语默认150词/分钟，中文240字/分钟，均为估算基准。全书排名首版按单一中文或英文剧本分别运行；混合语言输入会明确拒绝，避免把混合文本记为零词或套用错误语速。

只使用目标语言已核验的声音库，`mimo_default` 不增加容量。默认为旁白预留一个名额，其余名额优先给对白最多的角色；互动图决定这些角色之间的具体内置声音分配。自动分配不复用声音，用户明确锁定的共享分配保留。人工适配表若启用必须完整，缺项不能等同适合，不适合的自动分配不会强行通过。

其他角色使用固定声音卡，分成稀疏／反复出场两档。LLM 只生成身份描述和表演指令，不修改正文、对白归属或模型名。声音卡绑定书籍、角色、语言和版本。用户锁定字段保留；已分配声音不会被旧版音色轮换逻辑覆盖。

内置声音请求 `mimo-v2.5-tts`；描述声音请求 `mimo-v2.5-tts-voicedesign`，不传 `audio.voice`，关闭正文润色，使用非流式 WAV。正文始终放在 assistant 消息。普通合成、角色片段及可观测核心使用同一个模式解析器。缓存绑定有效模型、完整指令、文字、输出参数和声音卡版本。

描述角色不会自动把第一条生成音频认定为合格身份参考。人工确认后，固定参考供后续各章使用；音频内容、角色、语言或声音版本不符时不能沿用。声纹、音高及语速阈值仍只提示疑似异常。

## 命令顺序

以下命令从项目根目录运行，示例文件名需要替换成实际全书剧本。输入剧本应先完成别名合并和对白归属核验。

```sh
./venv_audio_quality/bin/python -m audiobook_generator.audio_core hybrid-usage \
  --script book.roles.json --language en --full-book --output role_usage.json

./venv_audio_quality/bin/python -m audiobook_generator.audio_core cast-hybrid \
  --script book.roles.json --language en --full-book \
  --bank voice_bank.en.json --output hybrid_casting.json

./venv_audio_quality/bin/python -m audiobook_generator.audio_core describe-hybrid \
  --script book.roles.json --casting hybrid_casting.json --output voice_cards.json

./venv_audio_quality/bin/python -m audiobook_generator.audio_core apply-hybrid \
  --script book.roles.json --casting hybrid_casting.json \
  --cards voice_cards.json --output book.hybrid.roles.json
```

`--full-book` 是调用方对输入完整性的明确声明，程序不会从局部章节猜测全书排名；没有该参数仍可导出局部统计，但不能自动全书分配。统计夹具和局部试听材料不能冒充真实全书研究数据。

`cast-hybrid` 支持 `--locks`（角色→内置声音或完整参数）、`--fit-penalties`（全部角色×全部有效内置声音）、`--no-reserve-narrator`。当前英语合格库只有 Mia、Chloe，默认预留旁白后仅剩一个普通角色名额。

`describe-hybrid` 实际调用一次已配置的 DeepSeek，无自动重试；同时保存 `voice_card_generation.json`，记录输入和原始返回。已有声音卡可直接应用，不必重调。`apply-hybrid` 检查原剧本指纹，不允许把旧分配套用至改过的正文。

## 声音先导与人工参考

```sh
./venv_audio_quality/bin/python -m audiobook_generator.audio_core probe-hybrid \
  --script book.hybrid.roles.json --roles role_a role_b --output new_probe_folder
```

首轮固定两个英语描述角色：每个角色两条共同文本，再独立重复第一条，共六次请求。重复明确绕过缓存；目录已有运行记录时拒绝重跑。失败时保留已完成样本和账本，不静默重试或换声音。

```sh
HF_HUB_OFFLINE=1 MODELSCOPE_OFFLINE=1 OMP_NUM_THREADS=1 KMP_USE_SHM=0 \
./venv_audio_quality/bin/python -m audiobook_generator.audio_core evaluate-hybrid-probe \
  --manifest new_probe_folder/probes.json --output new_probe_folder/quality.json \
  --review-dir listening_review/new_probe \
  --asr-model .audio_quality_models/SenseVoiceSmall --speaker-model .audio_quality_models/ecapa \
  --bank voice_bank.en.json
```

此步骤不合成。输出六条正文、自动检查、声纹比较以及可直接播放的本地 HTML 页面。`--bank` 可选，用已有相同文本和相同声纹模型版本的内置探针对比，无须重合成内置声音。声纹距离不能代表听众辨识率。

试听先核对内容，再比较同角色三条是否稳定，最后判断两个角色能否区分。每个角色选一条身份清晰、内容完整和信号合格的音频，把待核验 JSON 中该条的三项确认填写为 true，组成只有两条的 `reference_reviews.confirmed.json`，保留原始待核验文件。随后：

```sh
./venv_audio_quality/bin/python -m audiobook_generator.audio_core confirm-hybrid-references \
  --quality new_probe_folder/quality.json --reviews reference_reviews.confirmed.json \
  --output role_references.json
```

导入会核对角色、声音版本和音频 SHA256。不得将同一角色多条样本都作为“固定身份参考”。合成书籍时将生成的角色剧本交给原来的 `--role_script`，并在统一核心中加：

```text
--tts openai --audio_core_enabled --audio_core_role_references role_references.json
--audio_core_asr_model .audio_quality_models/SenseVoiceSmall
--audio_core_speaker_model .audio_quality_models/ecapa
```

网页入口同样支持这份固定参考：上传 `book.hybrid.roles.json` 作为角色剧本，开启统一质量核心，在“本地模型与资源设置 JSON”中填写 `role_references`。建议使用本机绝对路径，例如：

```json
{
  "role_references": "/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/audiobook_output/mimo_hybrid_plan_20261017/role_references.json",
  "asr_model": "/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/.audio_quality_models/SenseVoiceSmall",
  "speaker_model": "/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/.audio_quality_models/ecapa"
}
```

上面的参考库只适用于本轮声音档案及版本，不能直接套用到另一部书或新声音卡。`role_references: null` 表示不指定固定参考，此时描述角色的一致性检查仍可能不完整。此路径读取服务器上的文件；仅上传设置 JSON 不会连带上传参考音频。

若新声音卡改变、参考被替换或音频文件损坏，需要重新核验；不会自动换回 Mia。固定描述直接合成不保证身份稳定，若先导确有漂移，应先修订有版本的声音卡或单独验证参考克隆，不能直接扩大到整书。

## 混合场景及响度匹配

用户核验描述声音后，才运行小规模场景：

```sh
./venv_audio_quality/bin/python -m audiobook_generator.audio_core run-hybrid-scenes \
  --script mixed_scenes.json --references role_references.json --output new_scenes_folder \
  --asr-model .audio_quality_models/SenseVoiceSmall --speaker-model .audio_quality_models/ecapa

./venv_audio_quality/bin/python -m audiobook_generator.audio_core prepare-hybrid-loudness \
  --manifest new_scenes_folder/manifest.json --output matched_folder
```

首轮场景最多三章、16个合成块，不自动修复，已有输出目录拒绝重跑。响度处理只从原始场景报告生成来源绑定副本，不覆盖原版；跨度大于12dB会停下供检查。处理后逐章对 `descriptor.json` 运行 `evaluate`，固定参考和实际请求条件随报告保存；旧报告缺少这些条件时不得猜测。匹配版没有继承原版或共同探针的人工结论，需要重新试听。

## 本轮材料与边界

锁定声音以V2来源剧本为准。应用分配时会重新检查来源锁定状态；即使手改清单为未锁定，也不能替换来源中已锁定的既有参数。描述声音的描述、档案ID和版本同样受检查。修改声音应先明确修订来源档案，保留版本和核验记录。

- 构造统计及声音卡：`audiobook_output/mimo_hybrid_plan_20261017/`。十二章夹具仅检验排名、间隔和容量，不是研究语料。
- 六条真实合成及机器报告：`audiobook_output/mimo_hybrid_probe_20261017/`。6次请求、520个正文字符，未自动重试。
- 试听页：`listening_review/hybrid_voicedesign_20261017/index.html`。`lead_1/2/3` 为 Morgan；`guest_1/2/3` 为 Taylor；第3条均独立重复第1条。
- ASR 六条正文一致，信号检查均通过；用户确认“内容完整、同角色一致、两角色容易区分”。两条未校准 `speaker_drift` 提示保留，人工反馈另存于 `human_acceptance_v33.json`，绑定实际音频与报告。已为两名角色分别建立一个固定参考。
- `mixed_scenes.pending.json` 是本轮合成输入，其文件名保留原准备阶段命名。三章已生成于 `audiobook_output/mimo_hybrid_scenes_20261017/`，11次新请求、584个正文字符，无自动修复或隐藏重试。章节编号只表示自编测试场景，不是已经转换的真实书籍。
- 描述角色的5个新句均正确引用原固定参考；三章导出验证逐样本一致。原版机器留下第1章 Bring、第8章 Follow、Taylor跨章声纹和第4章旁白语速提示。用户随后针对三章音量匹配版确认“**三个章节均无上述问题**”：Bring／Follow完整，Taylor在H01/H03声音一致，接缝和音量自然，H02旁白语速可接受。该结论单独绑定这三条文件及复评报告的SHA256，保留全部机器证据，不沿用六条共同探针的结果消除新告警，也不修改原版报告。
- 已独立测量11段响度，原版跨度约11.5dB；另存 `audiobook_output/mimo_hybrid_scenes_matched_20261017/`，以本次最轻声的一句 -25.41 LUFS 为目标，只整句衰减、不放大，保留时间位置。复评后11段响度范围约 -25.43～-25.39 LUFS，三章PCM保留检查通过，人工参考也在复评中沿用。此目标只用于本轮材料，不是新的全局默认。
- 新章节试听页 `listening_review/hybrid_mixed_20261017/index.html`：H01/H02/H03分别对应第1/4/8章，总长42.73秒，含匹配版、原版、正文位置及同角色参考。
- 原九章内置声音对照、-5dB人工反馈及中文100ms起读样本均保留；本轮新设计声音没有套用这些来源特定的增益设置。
- 新章节来源绑定核验：`listening_review/hybrid_mixed_20261017/human_acceptance_v34.json`，填写后的检查项见 `chapter_reviews.confirmed.json`，原始待核验模板保持不变。H02没有被单独询问跨章同角色辨识，相关字段仍留空。
- 正式转换入口已用两章离线夹具验证：读取角色JSON、保留每角色模式、任务pickle传递、固定参考跨章复用、PCM和质量报告输出；仅替换外部合成返回，不能据此证明真实音质。网页设置现支持 `role_references`。回归558项：528通过、30按环境跳过，无失败；本轮未增加在线调用。

## 听众辨识材料的声音身份核对（v50）

`prepare-listening` 现同时核对内置、描述、克隆三种声音模式。跨场景的同一角色必须保持相同声音档案、版本和实际请求条件；描述／克隆必须有对应实际请求记录。克隆同时检查参考文件内容指纹，不以文件路径相同代替内容一致，相同内容的合法副本可共用身份。公开材料不含档案、模式、模型或选角方案，来源和答案只存私有文件。

这是实验配置门禁，不能证明实际音色稳定或听众易辨认。新旧音频的人工接受不能自动互换；导出仍需通过内容、信号及来源完整性检查，并由实验者审查质量可比性。五项新增回归后，全量602项中572通过、30环境跳过；Flipped首章100块（三种模式）和已接受混合场景11块的真实身份记录核对通过，四个角色跨三个混合场景的配置一致，没有新增合成。

内置声音对照的36题待审包位于 `audiobook_output/casting_listener_pilot_20261017/`，只分发其 `public/` 子目录。此包仍为描述性先导，回答未填写。互动图方案与随机方案在本批的分配相同，合并为一个条件，不能用它比较二者优劣。T01／T02的人工确认只解除两处完整上下文的ASR误报，未宣称九章完整试听通过。

接口依据：[MiMo 官方语音合成文档](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5)。
