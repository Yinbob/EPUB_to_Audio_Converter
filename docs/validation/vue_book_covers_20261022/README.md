# 恢复旧版宽度与书籍封面上传

## 宽度依据

Git 提交 `63aa489`（新增多角色对话生成功能），`audiobook_generator/ui/web_ui.py`：

- 常规宽度 100%，两侧 `clamp(14px, 4vw, 48px)` 留白。
- 视口 ≥1200px 时容器最大 1280px。
- 视口 ≥1440px 时容器最大 1320px。

Vue 已移除固定 1040px 限制，沿用上述规则；手机仍保留 14px 留白。

## 上传与封面

上传区展示书籍缩略图、名称、大小及移除按钮，支持批量。EPUB 读取 EPUB 3 cover-image、EPUB 2 cover 元数据及 guide 封面页；DOCX 优先读取文档缩略图，否则使用正文首张内嵌图片。旧 DOC、缺少封面和图片损坏时展示带书名的占位封面。图片只从压缩包内部读取，限制 XML、图片尺寸和体积，生成 JPEG 缩略图并使用登记 ID 访问，不读取远程封面或解压到客户端路径。

上传返回后卡片以 240ms 的 transform/opacity 轻浮入，图片加载完成后淡显。移除时淡出，列表位置平滑调整；减少动态效果时只保留 120ms 淡显。上传区保留最小高度，避免单本上传引发页面大幅跳动。目录继续自动读取，模型和正文解析机制不变。

## 验证

- 前端类型检查与正式构建通过。
- `./venv_audio_quality/bin/python -m unittest discover -s tests/services -p '*_test.py'`：26 项通过，含 4 项新封面测试。
- `npm run test:e2e`：10 项通过（14.9 秒）。真实 EPUB 测试夹具验证上传、图片读取、自动目录；另验证多本占位、长文件名、移除、导航保留，以及 1600 / 1280 / 1100 / 390px 的宽度与无横向溢出。
- 检查 desktop-light.png、desktop-dark.png、mobile-light.png、batch-mobile-dark.png；其余视口截图同目录。
- 当前 7862 服务在无活动任务时重启，已加载新封面逻辑。未调用付费接口或语音模型。
