# 功能迁移对照

以下“已接入”表示代码与操作入口存在，不等同于该引擎或复杂流程已完成目标环境真实验收。旧界面行为依据当前代码（非过时上游 README），旧测试保持保留。新增功能集中在服务/API/Vue；原 `web_ui.py` 的业务回调保留兼容，生成生命周期及密码校验已改为共享适配。

| 功能 / 旧行为来源 | 新实现 | 已验证 | 尚需真实验收 |
| --- | --- | --- | --- |
| EPUB/DOC/DOCX 上传、解析、章节范围；web_ui/process_form、book_parsers | uploads/books API、Generate、指纹校验 | DOCX 真实解析、文件登记/边界、浏览器上传 | 代表性 EPUB/DOC 文档人工对照 |
| 六引擎参数与默认值；Provider 实现 | models/capabilities/books、EngineFields | 六引擎离线映射、非法字段拒绝；MiMo 实际 MP3 合成 | MiniMax、Edge、Qwen、Chatterbox、VoxCPM 真实合成 |
| 批处理、spawn 章节池、停止整组；_batch_worker | TaskManager/run_task；Gradio start_configs 适配 | 幂等启动、子孙进程终止、停止两次、日志镜像 | Linux/CUDA 中途停止和显存回收 |
| 进度、刷新恢复、终态隐藏；progress_parser/HEAD_HTML | 复用纯解析器、Pinia 2 秒轮询、稳定 DOM | 刷新恢复、停止、终态模式、无历史完成闪现 | 断网长时间恢复及长批次人工观察 |
| 日志首屏 800 行 / 2000 回滚；gradio_log | 任务独立日志、字节游标、Logs | 游标增量、脱敏、浏览器页面 | 超大日志滚动体验 |
| 角色 V1/V2 导入、拆分、复核、确认；role_studio/review | Projects、RoleStudio、split 任务 | 真实 DeepSeek V2 拆分；导入、版本冲突、确认失效、外部编辑、取消迟到结果 | 大书跨范围续拆、取消交错完整人工流程 |
| 旁白、归属、人物合并、声音锁；review | project PATCH 操作、角色复核页 | 核心既有单测、API 编辑与浏览器确认 | 全部复核组合的浏览器人工验收 |
| MiMo 预设/设计/克隆、MiniMax 声音、语速校准；role_voices | 声音编辑、试听任务、固定试听参考、calibrate 任务 | 原声音核心回归、请求配置校验 | 真实角色试听、克隆、批量校准 |
| 全书分析 / 声音草稿 / 编辑应用；book_casting | casting_analyze/draft、casting status、可编辑草稿 | 复用原控制器回归、修订号与应用锁 | 真实全书分析→分配→生成 |
| 质量检查 / 自动修复 / 报告；audio_quality | 质量配置上传、生成开关、QualityPanel、报告音频 ID | 原质检核心回归、接口报告接线 | 真实质检修复后逐片试听 |
| 资源库、单文件/ZIP、删除；library_service | library/files API、Library 页面 | Range 206、ZIP、删除确认和路径边界、页面导航 | 浏览器多音频拖动与大 ZIP 下载 |
| API 配置 / 连接测试 / 密码；原配置模块 | settings API、HttpOnly 会话、Settings | 旧密码升级、密钥空值保留、清除/脱敏、跨站拒绝、登录退出 | 各提供商实际连接测试 |
| 字体、毛玻璃、双主题、渐变标题；theme.py | 原 tokens + 自有组件 CSS | 桌面/手机双主题截图、无页面异常、无手机横向溢出 | 新旧逐项对照、窄桌面、键盘全流程 |
| 鼠标光晕 / 生成跑马灯；ambient_background.py | 原算法导出、直接任务状态输入 | Canvas 渲染、固定 seed、原算法回归 | data-field 定量对照、低性能与触屏设备 |
| CLI / 解释器 / Docker / 回退 | main_ui --ui、原 bootstrap、Node 多阶段镜像 | 原 CLI 回归、源码分流、Gradio 适配日志与任务测试 | Docker 实构建、部署回退演练 |

限制与设计选择：单进程单重任务；普通编辑在任何重任务期间暂时禁止，比仅锁相关项目更保守。文件读取走登记 ID；自定义服务端目录保持可配置。表单草稿保留于当前页面/导航生命周期，仅非敏感 checkbox 偏好落盘；API Key 不存 localStorage。没有自动恢复中断任务、自动迁移数据、根据旧 PID 清理进程或 ZIP 完成即删除源文件的行为。
