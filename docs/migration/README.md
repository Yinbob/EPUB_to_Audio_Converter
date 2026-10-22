# Vue 工作台迁移说明

## 当前交付与切换状态

提供 Vue 3 / TypeScript / Vite / Pinia / Vue Router 前端、FastAPI 接口、独立应用服务及 Gradio 回退适配器。源码和静态构建产物均在仓库中。CLI、原凭证文件、模型缓存和音频目录沿用原位置，没有执行数据转换或删除已有资源。

**默认入口仍为 Gradio。** Vue 可显式启动；六引擎真实环境验收、Linux/CUDA 进程与模型验证、Docker 镜像实构建尚未全部完成，不能将当前交付视为已满足自动切换默认入口的门槛。功能接线、自动化结果与待验项见 [验收记录](validation.md) 和 [功能对照](features.md)。

## 启动、构建与回退

在已有项目 Python 环境中安装更新的依赖：

```bash
python3 -m pip install -r requirements.txt
./run_ui.sh --ui vue
# 或显式使用已配置的解释器
./venv_audio_quality/bin/python main_ui.py --ui vue --host 127.0.0.1 --port 7862
```

项目原有解释器选择机制保持有效；激活环境优先。没有本地模型也能打开工作台，只有执行对应任务才加载模型。地址仍为 `http://127.0.0.1:7862`，前端和 API 同端口。

仓库已附带 `frontend/dist`。修改前端后，在 Node 22.12+ 环境构建：

```bash
cd frontend
npm ci
npm run build
```

缺少 `frontend/dist/index.html` 时入口会直接给出构建说明。用户运行生产版本不需要 Node。开发时先以 `--ui vue --port 7863` 启动 Python，再在 frontend 运行 `npm run dev`；Vite 将 `/api` 代理到 7863，保留同源请求头。

回退时先正常关闭当前服务，再启动：

```bash
./run_ui.sh --ui gradio
```

两套入口共用任务管理和根目录 `.studio-runtime.lock`，不能同时运行。不要使用多个 Uvicorn worker；任务与管理员会话保存在一个应用进程中。不要绕过入口另行调用旧 `host_ui()` 来并行运行服务。CLI 仍可独立执行；避免让 CLI 与界面同时占用同一模型或输出目录。

Docker 采用 Node 构建阶段 + Python 运行阶段，入口保留原 CLI 参数分流：

```bash
docker build -t epub-audio-vue .
docker run --rm -p 7862:7862 epub-audio-vue --ui vue
```

生产环境应沿用现有凭证与输出卷挂载方案；构建上下文排除了真实凭证、本地虚拟环境和模型缓存。此环境未实际构建和运行 Docker 镜像。

## 数据与任务

- 原音频仍位于 `audiobook_output/`，资源库直接扫描已有批次；自定义输出目录通过已登记任务展示。
- 新元数据位于 `audiobook_output/.studio/`：上传登记、项目修订、任务快照、每任务独立日志和试听文件。不要在任务运行期间手工修改这些文件。
- 默认生成输出为 `时间_书名_任务短ID`，避免重复点击之外的独立任务互相覆盖；手工指定的输出目录保持有效。
- 角色剧本仍写入 `.role_projects/`，V1/V2 格式不变。新确认签名与修订号单独保存；从旧目录自动发现的项目应在 Vue 中复核确认后使用。
- 开始、编辑、确认和资源占用登记共用锁；请求 ID 重试返回原任务。停止是幂等操作，终止整个进程组。刷新或关闭浏览器不停止任务。
- 正常退出服务会停止任务。重启后旧非终态标记为中断；不会根据历史 PID 杀进程或自动续跑。
- 角色修改、重新拆分、外部文件变更使确认失效。生成前重新检查版本、确认、书籍哈希、正文与章节覆盖。拆分结果仅由主进程提交，停止后的迟到结果不提交。
- 日志每两秒轮询，首屏最近 800 行、页面最多保留 2000 行；日志与接口错误对已配置 API Key 脱敏。历史终态可在日志页查看，新会话不会弹出上次完成卡片。

## 配置与管理员

沿用 `.webui_settings.json`、`mimo_config.json`、`minimax_config.json`、`qwen_config.json`、`deepseek_config.json` 及原环境变量。凭证解析通过现有模块完成，并用回归固定当前实际的文件优先行为。不要按旧 README 中的描述重新排列优先级。

初始化不返回明文密钥。管理员登录后可查看、保存、清空与测试连接；空输入保留原密钥，清空使用单独操作。密钥和密码不写入浏览器本地存储。原 SHA256 密码登录成功后升级为 PBKDF2，Gradio 回退也支持升级后的格式。管理员会话采用 HttpOnly / SameSite Cookie，退出及改密后失效。仍保持个人或可信局域网的部署边界。

文件接口只接受已登记 ID，并检查符号链接和资源目录边界；音频支持 Range。ZIP 使用独立临时目录，准备完成或点击链接都不会自动删除源文件；清理必须通过资源库明确勾选并确认。

## 结构与维护

| 位置 | 职责 |
| --- | --- |
| `audiobook_generator/services/` | 配置、文件、角色项目、任务、子进程和设置；不导入 web_ui |
| `audiobook_generator/api/app.py` | `/api/v1`、权限、文件响应与 SPA 静态服务 |
| `frontend/src/views/` | 生成、资源库、日志、设置 |
| `frontend/src/components/` | 表单基础组件、引擎字段、角色工作台、质量报告 |
| `frontend/src/stores/studio.ts` | 后端任务镜像、轮询、断线恢复、请求幂等 |
| `frontend/src/styles/`、`ambient.ts` | 原设计令牌、双主题、玻璃材质、原浮点光场 |
| `tests/services/`、`frontend/tests/` | 服务、HTTP、进程、前端与浏览器回归 |

API 契约由服务导出并生成前端类型：

```bash
python3 frontend/tools/export_openapi.py
cd frontend
npm run types:api
npm run build
```

`frontend/tools/export_visuals.py` 从原 theme/ambient 模块提取设计令牌和绘制算法。再次生成后应格式化并重新验收。光场缓冲不进入 Vue 响应式系统；Vue 直接传入任务状态，保留原浮点累加、一次量化、逐通道抖动、重心锚定、色相环、跑马灯、隐藏页暂停和 reduced-motion。可用 `?ata-seed=123&ata-state=generating` 固定布局和预览生成态，诊断数据仍在 `#ata-bg.dataset.field`。

## 后续正式切换门槛

1. 在有凭证或模型的目标环境为六引擎分别完成短文本真实合成、试听、停止和资源下载。
2. 在 Linux/CUDA 验证本地引擎模型加载、试听释放、spawn 子进程及无孤儿停止。
3. 完成真实全书角色分析、声音分配、取消交错、质量修复与报告试听的人工操作验收。
4. 完成三档视口的新旧页面对照、光场 `data-field` 定量检查、Docker 实构建与回退演练。
5. 满足上述条件并记录后，将 `main_ui.py` 中 `--ui` 的默认值由 `gradio` 改为 `vue`，保留显式回退至少一个稳定发布周期。
