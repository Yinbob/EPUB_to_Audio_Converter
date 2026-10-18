# 本地音色库

此目录保存 VoxCPM 预设音色首次使用/试听时生成的参考音频（`preset_*.wav` + 指纹 `preset_*.json`），以及你手动放入的自定义参考音频。

## MiMo 已保存音色

`bryce_young_en.wav` 是《Flipped》首章已核验的 R001 青年男声参考，固定 SHA256 为 `0ef58edb31d5bb0f3a5111f1d36e6afb9ba9da022627ce11f446072bed912a14`。

WebUI「多角色配音 → 角色声音 → 声音来源：预设声音」中选择「青年男声 · Bryce（英语）」，点击「应用当前人物的声音设置」，再试听并确认剧本。应用时仅复制到输出目录的 `.voice_references`；试听或生成时通过已有 MiMo 克隆链路使用参考，不把此名称作为 MiMo 内置 voice 发送。

该 WAV 是本地资源，默认被 Git 忽略，迁移项目时请另行复制。原始备份在 `listening_review/flipped_full_chapter_20261017/audio/R001.wav`；它不会自动重新生成。

## 手动放入自定义音色

把 `.wav` / `.mp3` / `.flac` / `.m4a` / `.aac` 文件放进本目录，WebUI 的 VoxCPM 音色下拉会自动并入（显示为「xxx（自定义）」）。CLI 也可以直接传文件路径。

## 清理

生成文件默认被 `.gitignore` 忽略，不会进入版本库。VoxCPM 的 `preset_*` 缓存下次使用会自动重新生成；请保留已保存的 MiMo 参考音及其他手动音色，不要把整个目录作为可重建缓存删除。
