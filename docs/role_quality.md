# 角色有声书的逐段音频质量测评

## 使用方式

WebUI 的「多角色分段模式 → 生成音频质量测评」可启用逐段检测，并设置中文语速上限（默认 **4.3 汉字/秒**）。CLI 可添加：

```bash
python3 main.py book.epub output --tts openai --role_script role.json \
  --role_quality_enabled --role_quality_max_rate 4.3
```

此功能仅在角色剧本模式生效，默认关闭。音频在应用 MiMo `speed` 后、合并成章前测评。每章结果原子保存到输出目录 `role_quality_reports/chapter_000001.json`；每段有原文 SHA-256、每次尝试的指标、所选尝试和最终状态。输出音频仍使用原有章节命名。

## 评测与反馈闭环

1. 测量实际 PCM 音频的时长、有效发声区间中文汉字速率、削顶比例、静音比例和峰值电平。
2. 可选本地 FunASR/SenseVoice 转写，并与原文比较中文字符错误率（CER）或英文词错误率（WER）。缺失模型、模型下载失败或转写异常时记录 `asr_unavailable`，状态为 `incomplete`，**不把缺失检测当作通过**。
3. `failed` 的 MiMo 片段最多重新生成一次。`too_fast` 同时确定性降低后处理倍率；质量摘要发送给已有 DeepSeek 服务，模型只能从三个预设的清晰度提示补丁中选择，不能改写原文。DeepSeek 不可用时改用固定保守补丁，并在日志和报告中记录。
4. 两次都未通过时保留质量排序较好的版本，标记 `failed`，交给人工复核；不会无限重试或静默宣称通过。MiniMax 只测评并出报告，不自动改提示词。

启用 ASR 前需在运行环境安装 `funasr` 并准备 SenseVoiceSmall 模型；首次使用可能下载模型，占用额外 CPU/内存。多章节并行会在每个 worker 中独立加载模型，内存有限时请使用 `--worker_count 1`。DeepSeek 凭证可通过现有配置或 WebUI 输入提供；启用自动反馈会把失败段原文摘录（最多 350 字）、转写摘录和指标发给该服务。

## 指标边界与验收

`4.3` 是可调整的起始阈值，**不是普适的人类听感标准**。汉字/秒不适用于英文；CER/WER 是可辨识度的代理量，也会受到 ASR 本身错误、专有名词、古文和不同口音影响。削顶/静音阈值是工程性异常检测，不等同于 MOS。正式论文或出版流程应以人工听辨、误判率/漏判率、按体裁分层的标注集校准阈值，并比较「无 QA」「只调速度」「LLM 提示反馈」三种消融条件。

最小验收包括：过快片段确实变慢、原文不变、失败片段最多两次合成、通过片段不重试、ASR 缺失明确标 `incomplete`、重试仍失败保留报告、章节合并使用所选尝试的 speed。相关单测位于 `tests/audiobook_generator/role_script/audio_quality_test.py` 与 `tests/audiobook_generator/core/audiobook_generator_test.py`。
