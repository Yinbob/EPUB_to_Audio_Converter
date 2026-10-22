# 迁移验收记录

记录日期：2026-10-21。本机 macOS，项目 Python 3.11（venv_audio_quality）、Node 26、Google Chrome。没有 Linux/CUDA、完整本地引擎模型和 Docker 构建环境的验收结果。

## 已执行检查

| 检查 | 结果 |
| --- | --- |
| 原有及新增 Python 全量（显式包含 `*_test.py`） | 最终收集 770 项，740 通过、30 跳过，OK（20.769 秒） |
| 新增服务/HTTP/进程测试 | 22 项通过；临时目录、假任务、真实 DOCX 解析，不调用付费 API |
| Vue 类型检查和生产构建 | `vue-tsc --noEmit && vite build` 通过；dist 已生成，JS gzip 约 60 KB |
| Vitest | 6 项通过，包括失联重试复用请求 ID、API 错误、上传、新会话终态过滤 |
| Playwright 完整场景 | 4 项通过：四页双主题响应式、上传启动刷新停止、角色确认失效、管理员登录退出 |
| 最终浏览器功能复验 | 最终 3 项操作场景通过（3.2 秒），未重复覆盖已验收截图 |
| 源码检查 | 新服务/API 不导入 web_ui 或 Gradio；`git diff --check` 通过 |
| 真实 MiMo 小样本 | 成功生成单章 MP3，28434 bytes；测试使用临时目录，未留存用户音频 |
| 真实 DeepSeek 小样本 | 成功生成 V2 项目、revision=1、confirmed=false |

Python 完整命令：

```bash
python3 -m unittest discover -s tests -t . -p '*_test.py'
python3 -m unittest tests.services.studio_test
```

前端检查：

```bash
cd frontend
npm ci
npm run build
npm test
npm run test:e2e
```

浏览器夹具在临时目录启动端口 7864，用可控假任务与演示项目，既不读取真实密钥，也不调用模型。默认使用项目 venv_audio_quality；可用 `STUDIO_TEST_PYTHON` 指定解释器。macOS 默认系统 Chrome，其他平台使用 Playwright 浏览器或 `CHROME_PATH`。首次在无浏览器环境执行时需自行安装 Playwright Chromium。

真实冒烟脚本必须显式传入 `--live`，会调用付费接口；不要纳入默认测试：

```bash
python3 -m tests.services.live_smoke --live --provider openai --report /tmp/studio-mimo.json
python3 -m tests.services.live_smoke --live --provider openai --kind split --report /tmp/studio-split.json
```

实际支持参数以脚本 `--help` 为准。原始脱敏结果：[MiMo](live-mimo.json)、[DeepSeek](live-deepseek.json)。DeepSeek 原始报告暴露了“非生成任务成功时旧日志解析器给出 failed 模式”的显示问题；已改为由任务终态覆盖进度 mode，并用无日志标记的假任务回归固定。保留原报告作为发现记录，未为重复验显示而再次调用付费接口。

## 视觉产物

- [桌面浅色](screenshots/desktop-light.png)、[桌面深色](screenshots/desktop-dark.png)
- [手机浅色](screenshots/mobile-light.png)、[手机深色](screenshots/mobile-dark.png)

截图来自临时测试服务，固定布局随机种子；展示新界面，并非所有旧页面的一比一截图差异证明。当前只完成桌面 1440×1000、手机 390×844；窄桌面、新旧逐组件对照、光场 data-field 定量采样仍待验。

## 尚未通过的发布门槛

- MiniMax/Qwen 缺少凭证；Chatterbox/VoxCPM 缺少对应运行包/模型；Edge 真实远程合成未执行。六引擎均已完成离线配置验证，不能替代远程/模型真实冒烟。
- 未在 Linux/CUDA 上验证模型加载、试听释放、合成和整组停止；本机假任务停止测试不能代替 GPU 验收。
- 全书声音分配、校准、质量修复虽然已接入既有核心和新界面，尚需目标环境中的完整实际操作、费用受控的试听与报告检查。
- Docker 多阶段配置已修改，但未实构建；回退适配的单测和既有 UI 回归通过，实际部署切换演练尚未完成。

因此不修改默认 UI。正式切换的顺序和启动/回退说明见 [README](README.md)。
