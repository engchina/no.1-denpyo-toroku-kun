# Intent Classifier UI/UX 统一规范

本文档用于把当前系统已经存在的视觉语言（Oracle Redwood + 现有 aai/ics 样式）整理成一套可执行的统一方案，并作为后续页面与组件的实现基线。

## 目标

- 统一信息层级：页面标题、分区标题、内容正文、辅助说明、状态反馈层级明确且一致。
- 统一布局节奏：固定的页面间距与卡片内边距，避免同类页面“看起来像不同产品”。
- 统一组件外观：按钮、输入框、表格、状态徽章、上传/拖拽区域在所有页面一致。
- 提升可用性：键盘可操作、清晰的 focus 样式、减少误触与不可点击的伪链接。

## 设计基础（不要重复造轮子）

- 字体：使用 `--aai-font-family-primary` / `--oj-html-font-family`（已在 `app.css` 定义）。
- 颜色：优先使用 `--aai-*` 颜色 token；Ops 风格页使用 `--ics-*` token（由 `*.--enhanced` 容器提供）。
- 间距：优先使用 OJ 的 spacing utility（如 `oj-sm-margin-*` / `oj-sm-padding-*`），避免在 TSX 里写 `style={{ margin... }}`。

## 页面结构规范

每个功能页面建议保持固定骨架：

1. **根容器**：`<div class="{viewName} {viewName}--enhanced">`
2. **页面标题区**：使用 `.genericHeading` + `.genericHeading--headings__title/.subtitle`
3. **主要内容块**：
   - 表单/交互面板：`oj-panel` + 固定 padding（通常 `oj-sm-padding-7x`）+ `...View__panel`
   - 数据展示卡：`.ics-card`（配 `.ics-card-header`/`.ics-card-body`）
4. **表格区域**：`<table class="ics-table">`，需要粘性表头时使用 `.ics-table--sticky`

## 组件规范

### 按钮

- 业务按钮优先使用 Oracle JET Preact `Button`（一致的尺寸、禁用态、无障碍语义）。
- 非 JET 按钮（例如 Dashboard 的快捷跳转）必须用 `<button type="button">`，禁止用“没有 href 的 `<a>`”。
- 文案规则：
  - 操作型：动词开头（Predict / Train / Save / Refresh / Test）
  - 结果型：状态提示（Copied / Saved / Configured）

### 输入框 / 文本域

- 文本输入统一使用 `.ics-input`（包括 `input`、`textarea`）。
- 必须具备：
  - `label`（可见或语义关联）
  - `disabled` 时清晰的不可编辑视觉
  - `focus` 时清晰的边框高亮（由 `.ics-input:focus` 提供）

### 卡片与分区

- 信息分区优先使用 `.ics-card`：
  - 标题放 `.ics-card-header`
  - 内容放 `.ics-card-body`
- 需要“面板感”的区域可用 `oj-panel`，但同一页面不要混用多套“卡片”外观（除非明确有层级差异）。

### 表格

- 使用 `.ics-table` 统一表头字重、行高与分隔线。
- 大数据量/固定高度列表：
  - 外层容器限制高度并开启滚动
  - 表头使用 `.ics-table--sticky` 保持可见

### 状态徽章与反馈

- 页面状态：`.ics-status-badge` + `ics-status-*`（healthy/degraded/error/unknown）
- 行内状态：`.ics-badge-success/warning/danger/unknown`
- 异步加载：
  - 小范围加载：按钮 loading 状态（禁用 + icon spin）
  - 大范围加载：居中 loading row（ProgressCircle + 文案）

### 上传/拖拽区（Drop Zone）

- 视觉统一：图标、主提示、次提示的间距一致。
- 行为统一：
  - 点击触发 file input
  - drag over / leave / drop 正确切换激活态 class
  - 禁用态（训练进行中等）必须明确不可点击与半透明呈现

## 导航与信息架构（IA）

- Side navigation 负责全局一级页面切换：Dashboard / Statistics / Predict / Training / Model info / Application settings。
- 当前页面必须通过：
  - `aria-current="page"` 或 `aria-selected="true"`
  - 选中态背景与文字保持可见
- 折叠侧栏时：
  - 保留图标
  - label 隐藏但可通过 `aria-label` / `title` 获取（可访问性）

## 可访问性（A11y）底线

- 点击行为必须用 `<button>` 或带 `href` 的 `<a>`，禁止伪链接。
- 所有可交互控件必须可键盘操作并具备 `:focus-visible` 样式。
- 任何只靠颜色表达的状态，必须同时有文案（例如 “Healthy / Error”）。

## CSS/实现约定

- 样式集中在 `denpyo_toroku/ui/src/styles/app.css`，新增样式优先：
  - 放在对应 view 的 block 附近（`predictView__*`、`trainView__*` 等）
  - 采用“语义 class”替代 inline style
- 允许的 inline style：
  - 仅用于必须运行期计算的值（例如根据页大小计算的 `maxHeight`）
  - 其余常量间距/颜色/布局一律用 class 统一

