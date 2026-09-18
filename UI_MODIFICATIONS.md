# UI 修改记录

## 修改日期
2026-09-07

## 修改目标
1. 统一配色，特别是浅灰色框
2. 优化高级设置按钮样式
3. 使用 ui-ux-pro-max skill 美化 UI
4. 整体风格类似 Apple 网页设计

## 修改内容

### 1. 统一配色方案

#### CSS 变量修改
- **主背景**：`--apple-bg: #fbfbfd`（原为 `#f5f5f7`）
- **卡片背景**：`--apple-surface: #ffffff`（保持不变）
- **次要背景**：`--apple-surface-2: #fbfbfd`（保持不变）
- **边框**：`--apple-border-soft: #e8e8ed`（保持不变）

#### 灰色使用规范
- **输入框背景**：`#f5f5f7`
- **按钮背景**：`#f5f5f7`
- **按钮悬停**：`#ebebed`
- **边框**：`#e8e8ed`
- **主背景**：`#fbfbfd`

### 2. 高级设置按钮优化

#### 添加的 CSS 样式
```css
/* ── 高级设置按钮优化 ── */
.modal-trigger {
  background: var(--apple-surface) !important;
  color: var(--apple-text) !important;
  border: 1px solid var(--apple-border) !important;
  border-radius: 14px !important;
  font-weight: 500 !important;
  font-size: 0.95rem !important;
  padding: 14px 24px !important;
  transition: all 0.2s ease !important;
  cursor: pointer !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 8px !important;
}

.modal-trigger:hover {
  background: var(--apple-surface-2) !important;
  border-color: var(--apple-border-soft) !important;
  transform: translateY(-1px);
  box-shadow: var(--apple-shadow) !important;
}

.modal-trigger:active {
  transform: translateY(0);
}

.modal-trigger::before {
  content: "⚙️";
  font-size: 1.1rem;
}
```

#### 按钮 HTML 修改
- 移除了内联样式，使用 CSS 类控制样式
- 保持了原有的弹窗功能

### 3. Apple 设计原则应用

#### 已有设计特点
1. **胶囊形状按钮**：使用 `border-radius: 980px` 或 `14px`
2. **平滑过渡**：使用 `transition` 和 `cubic-bezier` 缓动函数
3. **阴影效果**：使用 `var(--apple-shadow)` 和 `var(--apple-shadow-blue)`
4. **留白设计**：使用 `clamp()` 函数确保响应式留白
5. **字体选择**：使用 `-apple-system, BlinkMacSystemFont, "SF Pro Display"` 等系统字体

#### 无障碍标准
- 主要文本对比度：15.3:1（远高于 4.5:1 的要求）
- 次要文本对比度：4.75:1（略高于 4.5:1 的要求）
- 焦点状态可见：使用蓝色阴影指示焦点
- 响应式设计：支持不同屏幕尺寸

### 4. 响应式设计

#### 媒体查询
- `@media (max-width: 560px)` - 移动设备优化
- `@media (min-width: 560px)` - 平板设备优化
- `@media (max-width: 480px)` - 小屏幕优化
- `@media (max-width: 720px)` - 中等屏幕优化
- `@media (max-width: 520px)` - 特定屏幕优化
- `@media (pointer: coarse)` - 触摸设备优化
- `@media (hover: none)` - 无悬停设备优化
- `@media (prefers-reduced-motion: reduce)` - 减少动画优化
- `@media (min-width: 1200px)` - 大屏幕优化
- `@media (min-width: 1440px)` - 超大屏幕优化

## 测试结果

### 语法检查
- Python 语法检查：✅ 通过
- CSS 语法检查：✅ 通过
- 模块导入检查：✅ 通过

### 功能检查
- 高级设置弹窗功能：✅ 正常
- 按钮样式：✅ 已优化
- 配色统一：✅ 已完成

## 符合 Apple 设计风格的特点

1. **简洁性**：移除了不必要的内联样式，使用 CSS 类控制样式
2. **一致性**：统一了灰色配色方案
3. **可访问性**：确保了足够的对比度和焦点状态
4. **响应式**：支持不同屏幕尺寸
5. **动画效果**：使用了平滑的过渡动画

## 后续建议

1. 可以考虑添加深色模式支持
2. 可以考虑添加更多的微交互效果
3. 可以考虑优化移动端体验
4. 可以考虑添加更多的 Apple 设计元素（如模糊效果、渐变等）

---

## 氛围背景层 + 毛玻璃（2026-09）

实现文件：`audiobook_generator/ui/ambient_background.py`（`AMBIENT_LAYER_HTML` / `AMBIENT_CSS` / `AMBIENT_ENABLED`），
由 `audiobook_generator/ui/web_ui.py` 拼到 `HEAD_HTML` 与 `CUSTOM_CSS` 末尾。

### 分层

```
html/body 兜底渐变（background-image + background-color，不能用带 var() 的多值简写）
  └─ #ata-bg（position:fixed; z-index:0; pointer-events:none）
       ├─ #ata-bg-base      静态环境光渐变（生成态叠加 ::after 加强约 1.6 倍）
       └─ #ata-bg-canvas    canvas 光晕（预渲染 sprite + drawImage）
  └─ .gradio-container（position:relative; z-index:1; 背景透明）→ 卡片等内容
```

状态机：`idle → arming`（点「开始生成」）`→ generating`（进度条 `active/starting/running`）
`→ settling`（`done/warn/collapsed` 或「停止转换」）`→ idle`。

### 白底清理规则（关键）

- 卡片内布局包装层 `.block / .wrap / .form / .panel / .contain / .styler / .gr-group / .gr-box / .gr-form` → **透明**。
- 交互面（上传拖放区、开关行、幽灵/危险/迷你按钮、输入框/文本域/下拉、引擎分段选择器、
  文件组件标题标签与悬浮图标按钮）→ `rgba(255,255,255,0.45)`；弹窗内输入框 `0.55`。
- 阅读面：日志终端 `.xterm-viewport/.xterm-screen` `0.42`、资源库空态 `.lib-empty` `0.35`、
  Gradio 文件预览表格行 → 透明。
- 高级设置弹窗：`.modal-box` 透明 + 玻璃画在 `::before`（避开 `backdrop-filter` 包含块问题）。
- **必须保持不透明**：下拉选项面板 `ul.options`、`.modal-box` 之外的遮罩层。

### 验证清单（每次改 UI 后照做）

1. 四个页面（转换/资源库/日志/设置）扫描卡片内 `backgroundColor` 为不透明浅色的元素，应为 0；
2. 5 个引擎面板、高级设置弹窗、**已选文件状态**（文件列表行）、有内容的资源库列表同样扫描；
3. 鼠标停在页面不同位置截图，卡片内外的蓝偏应同步变化（证明玻璃在透背景，而不是被白填充盖住）；
4. 生成态：边框蓝偏 − 中心蓝偏应为明显正值（当前约 +13），空闲态接近 0；
5. 纯背景条相邻像素跳变 ≤2（无条带/断层）；`tests/audiobook_generator/ui` 全绿。

## 深色主题（2026-09）

实现文件：`audiobook_generator/ui/theme.py`（`THEME_TOKENS_CSS` / `THEME_CSS` / `THEME_HEAD_HTML`），
由 `web_ui.py` 拼进 `CUSTOM_CSS` 与 `HEAD_HTML`；顶栏按钮 `#ata-theme-toggle` 循环
**跟随系统 → 浅色 → 深色**（localStorage `ata-theme`）。

### 设计令牌

| 用途 | 浅色 | 深色 |
| --- | --- | --- |
| 页面底 `--apple-bg` | `#f5f5f7` | `#0e0e12` |
| 文字 `--apple-text` / `-2` / `-3` | `#1d1d1f` / `#5f5f66` / `#6a6a72` | `#f5f5f7` / `#c3c3c9` / `#a5a5ad` |
| 卡片玻璃 `--ata-glass` | `rgba(255,255,255,.58)` | `rgba(30,30,37,.62)` |
| 顶栏 / 进度条玻璃 | `.62` 白 | `rgba(18,18,23,.68)` / `rgba(32,32,39,.66)` |
| 控件面 `--ata-glass-soft` | `rgba(255,255,255,.45)` | `rgba(255,255,255,.07)` |
| 弹窗玻璃 `--ata-glass-modal` | `rgba(255,255,255,.82)` | `rgba(24,24,30,.86)` |
| 强调色 `--apple-blue` / 绿 / 红 | `#0071e3` / `#1f7a35` / `#d70015` | `#409cff` / `#4cd964` / `#ff8a82` |

### 两个必须知道的实现点

1. **暗色钩子复用 Gradio 的 `body.dark`**：Gradio 前端的主题 CSS 写成 `:root .dark{}`，我们挂同一个
   选择器（外加 `:root.dark` 用于首屏不闪白），这样自有组件与 Gradio 组件同时翻转。
   Gradio 自带文字变量（`--body-text-color-subdued` 等）默认是 slate-400，浅底上仅 2.48:1，
   已在 `:root` 与 `:root:root .dark`（提高一级特异性）里重映射到本项目文字令牌。
2. **日志终端只反相文字层**：xterm 用 canvas/DOM 渲染、主题色写死在组件里（浅底深字）。
   暗色下给 `.xterm-screen` 加 `invert(1) hue-rotate(180deg)`，底色放在不会被反相的
   `.xterm-viewport`（`--ata-terminal`）。若连 `.xterm` 一起反相，底色会被反成亮板。

### 可读性验证（改配色后照做）

- 用浏览器实测每页所有含文字元素的对比度（前景色叠加到最近的不透明背景上算 WCAG 比值）：
  正文 ≥ 4.5:1、大字号（≥24px 或 ≥18.66px 粗体）≥ 3:1 —— 两套主题 × 四页当前均为 0 处不达标；
- 终端、渐变标题、蓝色按钮等"取不到背景色"的元素用像素法复核（终端实测 13–14:1）；
- 单元测试 `tests/audiobook_generator/ui/theme_test.py` 会直接算两套调色板的对比度，
  改坏配色会立刻失败。

### 光晕平滑度与点击扩散（2026-09）

**断层问题的根因**：低透明度的全屏渐变在 8bit 下必然分档——实测右侧空白条带上出现 27 段"平顶"
（平均每 20px 才跳 1 级、最长 403px），肉眼就是一圈圈色带。

**三道防线**：

1. 色相从 24 档提到 32 档，并在相邻两张 sprite 之间按比例交叉淡入（`drawGlowSprite`）；
2. sprite 边长 160 → 224px，降低放大倍率；
3. 每帧最后铺一层预烘焙的抖动噪声（黑白各半、alpha 6 ≈ ±3/255，平均亮度为 0），
   把色带边界打散。

**效果（右侧空白条带 580px 剖面）**：

| 指标 | 改前 | 改后（深色） | 改后（浅色） |
| --- | --- | --- | --- |
| 平台段数(最长) | 27 段 / 403px | 8 段 / 1px | 16 段 / 2px |
| 取值档数 | 43 | 182 | 185 |
| 相邻像素变化比例 | 8% | 97% | 97% |

**点击「开始生成」的动效**（对齐 travel-agent 主页面）：

- 扩散起点 = 点击瞬间的鼠标位置（`spreadAnchorX/Y`），方向按黄金角均匀铺开，
  从光标向视口四周边框飞出，中心光晕同步淡出、边缘光晕淡入并缓慢呼吸；
- 同时整页平滑滑回最顶端（`window.scrollTo({top: 0, behavior: 'smooth'})`）。

**验证方法（可复现）**：点击前后在同锚点、同滚动位置各抓一帧，比较四角探针与
16 个方向的光晕半径；实测四角分别 +29~+41 色阶，12–13/16 个方向的光晕延伸到 490px 以上，
页面 scrollY 从 1262 回到 0。
