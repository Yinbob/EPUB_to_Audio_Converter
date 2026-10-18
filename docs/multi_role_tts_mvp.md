# 多角色分段 TTS MVP

状态：**已实现并接线**。普通单音色路径保持兼容；只有传入 `role_script`（CLI）或开启 WebUI 角色模式时，才进入多角色分支。

- 支持 Provider：MiMo（内部 ID `openai`）与 MiniMax。
- 一章最终输出一个音频文件，不保留角色分轨。
- 一个 `RoleScriptV1` 只绑定一本书，剧本由人工或外部工具生成。
- 角色模式依赖 `ffmpeg` 与 `ffprobe`，最终格式只允许 `mp3`、`wav`、`flac`。
- `--preview + --role_script` 是无凭证校验模式：读取书籍、校验剧本、输出章节摘要后退出，不创建 Provider。

接口基线：

- JSON Schema：[`docs/role_script_v1.schema.json`](role_script_v1.schema.json)
- 结构示例：[`examples/role_script.example.json`](../examples/role_script.example.json)

> 示例文件中的 `book_sha256` 是全零占位值，章节文本也不是正式书籍正文，不能直接用于转换。

## 1. 快速开始

### 1.1 准备环境

```bash
ffmpeg -version
ffprobe -version
```

MiMo 使用项目现有的 `openai` Provider 配置；MiniMax 使用现有 MiniMax 凭证配置。角色模式不会在父进程创建 Provider，章节 worker 才会读取凭证并初始化客户端。

### 1.2 计算书籍指纹

`book_sha256` 必须是对输入文件**原始字节流**计算的 64 位小写 SHA-256：

```bash
shasum -a 256 path/to/book.epub
# Linux 也可以使用：
sha256sum path/to/book.epub
```

### 1.3 编写或生成剧本

最小结构如下：

```json
{
  "schema_version": 1,
  "provider": "openai",
  "book_sha256": "<替换为书籍的 64 位 SHA-256>",
  "default_pause_after_ms": 250,
  "roles": {
    "narrator": {
      "display_name": "旁白",
      "provider_params": {
        "voice": "冰糖",
        "instructions": "用沉稳、清晰的中文有声书旁白语气朗读。",
        "speed": 1.0
      }
    },
    "lin_daiyu": {
      "display_name": "林黛玉",
      "provider_params": {
        "voice": "茉莉",
        "instructions": "声音年轻、克制、略带敏感，不要夸张表演。",
        "speed": 0.95
      }
    }
  },
  "chapters": [
    {
      "chapter_index": 1,
      "title": "第一章标题",
      "segments": [
        {
          "role_id": "narrator",
          "text": "这一段的正文必须与解析后的章节正文完全对应。",
          "tone": "平静"
        },
        {
          "role_id": "lin_daiyu",
          "text": "没有显式 pause_after_ms 时使用 default_pause_after_ms。",
          "tone": "克制",
          "pause_after_ms": 0
        }
      ]
    }
  ]
}
```

### 1.4 CLI 转换

```bash
python3 main.py path/to/book.epub output_folder \
  --tts openai \
  --role_script path/to/role_script.json \
  --output_format mp3
```

MiniMax 示例：

```bash
python3 main.py path/to/book.epub output_folder \
  --tts minimax \
  --role_script path/to/role_script.json \
  --output_format mp3
```

只转换指定章节：

```bash
python3 main.py path/to/book.epub output_folder \
  --tts openai \
  --role_script path/to/role_script.json \
  --chapter_start 2 \
  --chapter_end 5 \
  --output_format wav
```

无凭证校验：

```bash
python3 main.py path/to/book.epub output_folder \
  --tts openai \
  --role_script path/to/role_script.json \
  --preview
```

角色模式必须显式选择与剧本 `provider` 一致的 `--tts`。`--use_pydub_merge` 会被忽略并记录 warning，因为角色模式使用独立音频管线。

### 1.5 WebUI

启动：

```bash
python3 main_ui.py
```

操作步骤：

1. 选择一个书籍文件。角色模式首版只允许单本书。
2. 在引擎标签中选择 **MiMo** 或 **MiniMax**，并设置该引擎的输出格式。
3. 在生成页第 3 步的独立**多角色配音**模块，开启「为旁白和人物使用不同声音」。
4. 在「准备剧本」中展开 DeepSeek 连接配置，填写或使用已保存的配置，点击「生成 / 重新拆分剧本」。也可展开「上传或下载剧本 JSON」，上传已有的 `RoleScriptV1` JSON。上传后自动拆分默认关闭，按需开启。
5. 在角色参数表中检查或修改 `voice` / `voice_id`、`speed`、`instructions`、`pitch`、`volume` 等值。修改后的角色表会在内存中回写到剧本，不会改写上传文件。
6. 选择角色和试听文本，点击「试听该角色」。MiMo 试听与正式章节使用相同的 ffmpeg `atempo` 倍率；MiniMax 已在服务端变速，不再重复变速。
7. 音色间快慢明显时，展开「MiMo 音色间语速校准」。先将旁白 `speed` 调到合适的节奏，使用同一段 20～400 字试听文本，点击「以旁白为基准校准语速」。每个角色会调用一次 MiMo，全部成功后才回填倍率；失败保留原参数。计算方式为 `角色原始时长 / (旁白原始时长 / 旁白倍率)`，无旁白时以首个角色为基准，倍率限制为 `0.25..4.0`。
8. 校准是同文时长估算，正式对白的语气、停顿和模型波动仍会影响语速。校准或编辑后逐角色试听，再点击「确认剧本与角色参数」，再到第 4 步点击「开始生成有声书」。音色目录导入和剧本容错选项均收在折叠区。
9. 进度以 `第 N 章 i/n 段` 展示。Provider 内部分块进度不会覆盖外层 segment 进度。

### 1.6 独立脚本自动获取英文音色（可选）

WebUI 和实际转换过程仍然不会联网抓取官网；如需更新官方英文音色，可在终端显式运行根目录脚本：

```bash
# 先预览，不写入目录
python3 fetch_english_voices.py --provider all --dry-run

# 只抓取 MiMo 公共文档中的英文音色（无需 API Key）
python3 fetch_english_voices.py --provider mimo

# MiniMax 需要 MINIMAX_API_KEY，或项目根目录 minimax_config.json
python3 fetch_english_voices.py --provider minimax

# 两个来源都抓取；只替换本次成功 Provider 的英文条目
python3 fetch_english_voices.py --provider all --replace
```

脚本行为：

- MiMo 从官方 v2.5 语音文档及其当前版本 chunk 中解析音色表，只保留 `Language=English`
  的行，并跳过会随集群变化的 `mimo_default`。
- MiniMax 调用官方 `POST /v1/get_voice`；只保留语言明确为英文、ID 以 `English_` 开头，
  或已在内置英文音色表中的条目。无法确认语言的条目会跳过并显示数量，不会猜测。
- 结果默认与 `.tts_voice_catalog.json` 中现有条目合并；抓取失败或结果为空时不会修改目录。
- `--replace` 只删除“本次抓取成功的 Provider + 英文”旧条目，其他 Provider 和其他语言仍保留。
- `--json` 可输出机器可读结果；`--source-url`、`--minimax-api-url` 和 `--timeout` 用于排障。
- 新音色不会自动改写已经生成的剧本；需要回到「多角色配音」模块点击“生成 / 重新拆分剧本”。

### 1.7 手动导入官网音色说明

除了上述独立脚本，也可以在 TTS 官网下载音色说明文档，或在浏览器中复制音色表格，
然后到**多角色配音 → 补充音色目录（可选）**中操作：

1. 上传文档，或直接把内容粘贴到文本框中；上传文件优先于粘贴内容。
2. 选择文档对应的 `MiMo` / `MiniMax` Provider。文档内自带 `provider` 列时可以选“自动识别”。
3. 文档没有语言列时，选择“英语 / 中文 / 粤语”作为默认语言；有语言列时优先以每一行为准。
4. 点击“解析并保存音色目录”，检查解析成功数量、语言分布和未识别语言的提醒。
5. 如果剧本已经生成，点击“重新生成”。只改音色目录不会自动改写已有剧本。

支持上传 `.json`、`.csv`、`.tsv`、`.txt`、`.md`、`.html` / `.htm`、`.docx` 和 `.pdf`；
PDF 解析依赖 `pypdf` / `PyPDF2` 或 `PyMuPDF`。也可以直接粘贴 CSV、TSV、Markdown 表格或：

```text
voice_id | display_name | language | gender | description
English_Foo | Foo | English | male | clear English narration
```

常用列名为 `voice_id`（也识别 `short_name`、`音色 ID`）、`display_name`（也识别 `name`、`音色名称`）、
`language`、`gender` 和 `description`。缺少 `voice_id` 的行会跳过；无法识别的语言会显示提醒，
导入后仍可在角色参数表中手动修改 `voice` / `voice_id`。

用户目录保存在项目根目录 `.tts_voice_catalog.json`（已加入 `.gitignore`），会覆盖同 ID 的内置音色。
重新生成剧本时，DeepSeek 会优先使用用户目录；英文书优先匹配标记为 `English` / `en` 的音色，
MiMo/MiniMax 的音色下拉框也会同步出现这些条目。点击“清空用户音色目录”可删除导入项并恢复内置音色池。

## 2. RoleScriptV1 规范

### 2.1 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | integer | 固定为 `1` |
| `provider` | string | `openai`（MiMo）或 `minimax` |
| `book_sha256` | string | 源文件原始字节的 64 位小写 SHA-256 |
| `default_pause_after_ms` | integer | 段间默认停顿，`0..60000`；最后一段后不追加 |
| `roles` | object | 大小写敏感的 `role_id -> RoleDefinition` |
| `chapters` | array | 章节脚本数组 |

### 2.2 章节与 segment

`chapter_index` 绑定的是：

> 书籍 parser 使用角色模式固定 break string 解析章节后，过滤 `text.strip()` 为空章节，再按顺序形成的 1-based 索引。

`title` 默认必须匹配 parser 最终 sanitized title。标题和正文都比较规范化后的文本；正文覆盖率规则为：

```text
NFKC
-> 统一换行符
-> 去首尾空白
-> 移除全部 Unicode 空白字符
-> 按顺序拼接所有 segment.text 后与 parser 章节正文完全相等
```

segment 字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `role_id` | 是 | 引用 `roles`；大小写敏感 |
| `text` | 是 | 只朗读该字段；不能为空 |
| `tone` | 否 | MiMo 会追加为语气指令；MiniMax 仅记录到校对文本和日志 |
| `pause_after_ms` | 否 | 覆盖默认段间停顿，`0..60000`；显式 `0` 会生效 |

停顿只插入 segment 之间，最后一段后的 `pause_after_ms` 不产生尾部静音。

### 2.3 MiMo 与 MiniMax 参数

| Provider | 允许字段 | 必填 | 范围与行为 |
| --- | --- | --- | --- |
| MiMo `openai` | `voice`, `instructions`, `speed` | `voice` | `speed` 为 `0.25..4.0`；不发送给 MiMo API，合成后用 ffmpeg `atempo` 保持音高 |
| MiniMax `minimax` | `voice_id`, `speed`, `pitch`, `volume` | `voice_id` | `speed` 为 `0.5..2.0`，`pitch` 为 `-12..12`，`volume` 为 `0..10`；API 中的音量字段为 `vol` |

未知 Provider 参数会直接报错，不会被静默忽略。角色没有定义的参数使用当前全局配置；MiMo 的 `tone` 会追加到有效 `instructions` 后。

### 2.4 fallback 与 override

- 缺失角色默认失败。
- `--allow_role_fallback` 开启后，缺失角色按 `narrator -> 当前 Provider 全局默认配置` 回落，并记录 warning。
- `narrator` 是保留 ID，但只有被引用或作为 fallback 目标实际需要时才定义。
- `--allow_role_text_override` 只跳过正文覆盖率检查。
- `--allow_role_title_mismatch` 只跳过标题一致性检查。
- override 不会跳过非法 JSON、未知字段、空 segment、非法参数、缺失章节、Provider 不匹配或书指纹错误。

## 3. 音频与缓存行为

每个章节按 segment 顺序处理：

1. 在章节 worker 内创建 Provider。
2. 段内长文本可由 Provider 分块，但分块绝不能跨越 segment 边界。
3. 每段最多尝试两次；成功后写入章节临时目录并原子替换缓存文件。
4. 用 `ffprobe` 探测每段实际格式、采样率、声道和时长，不能假定等于配置格式。
5. 用 ffmpeg 解码为 PCM；以首段的采样率和声道作为章节基准，后续段统一重采样/声道转换。
6. MiMo 的有效 speed 在这里通过串联 `atempo` 应用。
7. 按计划插入静音并串联所有 PCM，最终只编码一次。
8. 写入章节、作者、书名、章节号标签；标签失败会删除章节输出并使章节失败。
9. 成功、失败或中断都会在 `finally` 中清理章节临时目录。

缓存只存在于本章节临时目录，不提供跨进程持久付费缓存。缓存 key 包含 Provider、模型、有效参数、tone、文本和影响音频输出格式的请求参数。MiMo key 使用实际音色和完整朗读指令（包含统一节奏提示与语气），不包含后处理的 `speed`；改变倍率可复用原音频，改变继承的全局指令会重新合成。

## 4. 校验报告与错误码

读取和校验报告固定输出：

```json
{
  "ok": false,
  "schema_version": 1,
  "errors": [
    {
      "code": "text_coverage_mismatch",
      "path": "$.chapters[0].segments",
      "message": "第 1 章 segment 文本与书籍正文不一致",
      "severity": "error",
      "context": {"chapter_index": 1}
    }
  ],
  "warnings": []
}
```

常见错误码分组：

- 读取与 JSON：`read_error`、`invalid_json`、`duplicate_key`、`invalid_root`。
- 结构与字段：`missing_field`、`unknown_field`、`invalid_type`、`invalid_chapter`、`invalid_segment`、`empty_chapters`、`empty_segments`、`empty_roles`、`empty_segment_text`。
- 角色定义：`invalid_role`、`invalid_role_id`、`invalid_display_name`、`invalid_provider_params`、`invalid_provider_param`、`invalid_provider_param_type`、`unknown_provider_param`、`missing_provider_param`、`provider_param_out_of_range`。
- Provider 与版本：`unsupported_schema_version`、`unsupported_provider`、`provider_mismatch`、`unsupported_role_output_format`。
- 书籍对齐：`invalid_book_sha256`、`book_sha256_mismatch`、`invalid_chapter_index`、`invalid_chapter_range`、`duplicate_chapter`、`missing_chapter`、`invalid_chapter_title`、`title_mismatch`、`text_coverage_mismatch`。
- 停顿与语气：`invalid_default_pause`、`pause_out_of_range`、`invalid_pause`、`invalid_tone`。
- 角色引用：`invalid_segment_role`、`missing_role`、`missing_fallback_profile`。
- override warning：`title_mismatch_override`、`text_override`、`role_fallback`。

WebUI 会把错误码和 JSON path 直接显示在校验摘要中；CLI 会写入日志并终止本次转换。

## 5. 进度

角色模式使用专用外层标记：

```text
role_chapter_<chapter_index>_segment_<i>_of_<n>
```

`progress_parser` 优先识别该标记，并转换为“第 N 章 i/n 段”文案。没有外层角色标记时仍可回落到 Provider 内部分块标记；不新增前端状态枚举。

## 6. 模块边界

```text
audiobook_generator/role_script/
  models.py          # 可 pickle 的纯数据模型
  loader.py          # JSON 读取、重复键检测、结构解析
  validator.py       # 参数、章节身份、覆盖率、fallback 校验
  planner.py         # ChapterSynthesisPlan 和校对文本
  audio_pipeline.py  # ffprobe/ffmpeg、归一化、停顿、单次编码、标签
  progress.py        # 角色模式进度标记
  errors.py          # ok/schema_version/errors/warnings 报告
```

Provider 只实现 `synthesize_segment(text, profile, work_dir, progress) -> AudioArtifact` 和必要的兼容门面，不拥有章节合并策略。最终编排仍由 `audiobook_generator/core/audiobook_generator.py` 负责。

## 7. 验证与回归

全量测试：

```bash
python3 -m pytest tests -q
```

本仓库当前测试环境的实际执行示例：

```bash
PYTHONPATH="$PWD/venv/lib/python3.13/site-packages" python3 -m pytest tests -q
```

重点验收：

- 领域层：重复 JSON key、重复/缺失章节、空段、角色缺失、参数越界、书指纹、标题和正文覆盖率、各 override。
- Provider：MiMo/MiniMax mock 验证角色切换不串参数、段内分块、重试、实际格式和缓存命中。
- 音频：真实本地 WAV + ffmpeg 验证顺序、`250ms`、显式 `0ms`、重采样、最终单次编码、标签和清理。
- 编排：mock E2E 会先做 pickle round-trip，再验证章节输出、标签、进度和 `.role_tmp` 清理。
- 候选真实 API 小样本：凭证可用时至少跑一本小型中文 EPUB 的一章；无凭证时以 mock E2E 作为替代验收，不作为失败项。

专项 mock E2E：

```bash
PYTHONPATH="$PWD/venv/lib/python3.13/site-packages" \
  python3 -m pytest tests/audiobook_generator/core/role_script_e2e_test.py -q
```

## 8. 已知限制

- 不自动识别说话人，不自动生成或修复剧本，不自动推断角色。
- 不保留角色分轨，一章仍是一个最终音频文件。
- 只支持 MiMo（`openai`）和 MiniMax；Chatterbox、VoxCPM 等本地克隆引擎的角色参考音频暂不接入。
- WebUI 角色模式只支持单本书；CLI 可通过同一剧本转换指定章节范围。
- MiniMax 当前没有可验证的情绪字段，`tone` 不发送给该 API。
- 章节标题和正文必须与当前 parser 的最终输出对齐；parser 升级后可能需要重新校对剧本。
- WAV/FLAC 标签写入依赖 mutagen 对对应容器的支持；标签失败按章节失败处理。
- 不做跨进程持久付费缓存；同一段重复合成只在同一个章节 worker 临时目录内复用。
- 角色模式不支持 `pcm` 或无容器输出。
