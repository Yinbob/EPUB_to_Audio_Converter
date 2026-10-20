# DeepSeek 模型配置核对与迁移（2026-10-19）

## 核对

- 官方首次调用页：https://api-docs.deepseek.com/zh-cn/
- 官方停用公告：https://api-docs.deepseek.com/zh-cn/news/news260424/
- 当前请求参数：https://api-docs.deepseek.com/api/create-chat-completion/
- 官方 /models 文档：https://api-docs.deepseek.com/api/list-models/

旧模型名 deepseek-chat/deepseek-reasoner 官方公告停用日期为2026-07-24。当前官方推荐 deepseek-flash（目前为DeepSeek-V4.1-Flash-1017），另有 deepseek-v4-pro；OpenAI兼容base_url仍为 https://api.deepseek.com。

使用项目已有凭证读取官方 GET /models，HTTP200，仅返回 deepseek-flash、deepseek-v4-pro。本次没有发送书籍或运行chat completion，未输出密钥。

## 修改

- DEFAULT_MODEL改为deepseek-flash，并让人物索引、叙述分析、分段拆分复用统一默认值，删除运行代码中散落的deepseek-chat回退。
- 新模型默认开启思考模式；结构化拆分与连接探针显式传 thinking.type=disabled，避免迁移改变原非思考行为。统一覆盖音频诊断提示补丁请求。
- 自定义模型名保留，不强加官方thinking参数。历史论文数据和实验模型标识不改写。
- 当前本地 deepseek_config.json 原为官方base_url + deepseek-chat，已仅更改model字段为deepseek-flash；密钥、地址和其余字段不变。
- 前端模型输入提示引用统一默认值。连接探针增加20秒网络超时。

## 验证与边界

完整离线回归704项：674通过、30按环境跳过。新增测试核对全部脚本请求的模型参数、非思考设置、连接探针和自定义模型保留。日志 /tmp/deepseek_model_migration_full.log。

未进行真实新模型拆分或语音听感验收。旧模型名确需修复，但本次检查不足以断言之前八分钟等待完全由模型名引起。浏览器访问限制未绕过；本轮没有浏览器验收。
