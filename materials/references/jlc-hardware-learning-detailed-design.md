# JLC Hardware Learning 硬件学习画板详细设计

## 1. 文档状态

- 设计范围：`黑五EDA` 的 JLC Hardware Learning 硬件学习画板子系统。
- JLC Hardware Learning 基线：0.1.27，固定提交见 [`../manifests/integrations.lock.json`](../manifests/integrations.lock.json)。
- EasyEDA API 基线：`@jlceda/pro-api-types` 0.4.15。
- 设计基线：详细设计。
- 实施状态：M0-M4 已进入可执行实现；Widget 保存问题到生命周期回答、会话恢复和幂等画板操作的端到端链路已落地并由回归测试覆盖。画板视觉导入现采用“官方 Current Schematic PNG → 身份复核 → 原生视觉证据清单 → 同页插入”链路；EPRO 单页/全工程图像渲染因视觉效果不合格已按策略关闭。
- 运行边界：本设计不连接、不修改、不保存 EasyEDA 工程。

本文是 [`learning-canvas-architecture.md`](learning-canvas-architecture.md) 的详细展开。机器契约见 [`../contracts/learning-canvas-contracts.schema.json`](../contracts/learning-canvas-contracts.schema.json)，官方 API 路由见 [`../manifests/jlc-hardware-learning-api-map.json`](../manifests/jlc-hardware-learning-api-map.json)。

## 2. 设计结论

硬件学习画板采用“JLC Hardware Learning 轻量增强 + 融合 Skill 独立业务内核”的方案：

1. JLC Hardware Learning 保留 tldraw 画布、选区、标注和项目本地持久化。
2. 对 JLC Hardware Learning 做最小、向后兼容的 `hardware-learning` 模式扩展，隐藏生图入口并增加硬件提问入口。
3. 选区、截图和问题被归一化成 `LearningQuestion`，JLC Hardware Learning 不理解电路业务。
4. EasyEDA 证据只由 `OfficialEasyedaEvidenceProvider` 通过固定官方 API 清单读取。
5. `HardwareTutorEngine` 只消费归一化证据，输出带证据引用的 `TutorAnswer`。
6. 回写画板仅允许文本便签、矩形、高亮和箭头，不允许图片、HTML 或 Slides。

这种设计避免把 EasyEDA Bridge、硬件知识、BOM 或审查逻辑塞进 JLC Hardware Learning，也避免融合 Skill 依赖 JLC Hardware Learning 内部 React 组件。

## 3. 目标与非目标

### 3.1 目标

- 用户能在无限画布上放入原理图截图、EasyEDA 官方导出或数据手册图片。
- 用户能用框、箭头、自由笔和文字说明“具体想问哪里”。
- 支持解释选区、追踪信号、解释器件、分析电源路径、概念审查和方案比较。
- 能结合当前 EasyEDA 页面中的器件、引脚、导线、网络和网表提供证据。
- 回答区分事实、推断、未知项和安全提示。
- 学习记录与画板一起保存在当前项目，支持继续追问。
- JLC Hardware Learning、EasyEDA 证据层、硬件导师和 BOM/审查模块可独立升级。

### 3.2 非目标

- 不生成新图片，不根据标注修改图片。
- 不生成 AI HTML、Slides 或展示型网页。
- 不从学习画板直接修改 EasyEDA 原理图。
- 不把概念解释等同于 DRC、生产审核或可制造性放行。
- 不在第一版实现自动跨页追踪；每个问题只绑定一个页面 UUID。
- 不在第一版建立长期用户画像或云端学习档案。

## 4. 架构决策

| 编号 | 决策 | 原因 |
|---|---|---|
| ADR-LC-001 | JLC Hardware Learning 是 UI Provider，不是业务内核 | 降低上游升级耦合 |
| ADR-LC-002 | EasyEDA Bridge 只能被证据适配器调用 | 保持官方 API 与授权边界 |
| ADR-LC-003 | 默认只读、单页面、身份前后复核 | 防止活动页面变化造成证据混合 |
| ADR-LC-004 | 选区截图属于确定性渲染，不属于生图 | 允许准确表达框选范围，同时禁止生成式图片 |
| ADR-LC-005 | 回写采用白名单命令，不直接保存任意 tldraw snapshot | 防止模型构造任意或破坏性画布记录 |
| ADR-LC-006 | 学习记录存放在 Workbench 目录，JLC Hardware Learning 只保存引用 | 避免绑定 JLC Hardware Learning 内部存储格式 |
| ADR-LC-007 | 学习模式关闭 JLC Hardware Learning 遥测 | 原理图、问题和选区默认留在本地项目 |
| ADR-LC-008 | 先实现无分叉 MVP，再落最小兼容补丁 | 尽早验证学习流程，控制维护成本 |

## 5. 总体结构

```text
┌──────────────────────────────────────────────────────────────┐
│ JLC Hardware LearningLearningUI                                             │
│ tldraw / 图片 / 框 / 箭头 / 文字 / 问题输入 / 学习级别       │
└─────────────────────────────┬────────────────────────────────┘
                              │ LearningQuestion
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ LearningCanvasAdapter                                        │
│ 选区归一化 / 截图 / 资产引用 / 意图分类 / 会话绑定            │
└───────────────┬──────────────────────────────┬───────────────┘
                │ EvidenceRequest              │ Session events
                ▼                              ▼
┌───────────────────────────────┐  ┌───────────────────────────┐
│ OfficialEasyedaEvidenceProvider│  │ LearningSessionStore      │
│ API Registry / Bridge / UUID   │  │ questions/evidence/answers│
└───────────────┬───────────────┘  └───────────────────────────┘
                │ EvidenceBundle
                ▼
┌──────────────────────────────────────────────────────────────┐
│ HardwareTutorEngine                                          │
│ 图结构 / 问题路由 / 证据引用 / 分层解释 / 安全提示            │
└─────────────────────────────┬────────────────────────────────┘
                              │ TutorAnswer
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ CanvasAnswerPresenter                                        │
│ Codex 回答 + note/highlight/rectangle/arrow 白名单回写        │
└──────────────────────────────────────────────────────────────┘
```

## 6. 模块详细设计

### 6.1 `JLC Hardware LearningLearningUI`

职责：

- 渲染 JLC Hardware Learning 原生 Widget。
- 提供画板原生工具：选择、拖拽、缩放、图片、画笔、文本、箭头、便签、矩形、高亮。
- 显示“硬件学习模式”状态。
- 获取问题、学习级别和快捷问题意图。
- 计算准确的页面坐标边界并生成选区截图。
- 通过 `ui/message` 提交 `LearningQuestion` 和截图附件或本地资产引用。

学习模式下必须隐藏：

- AI 图片。
- AI HTML。
- AI Slides。
- 按标注改图。
- 所有生成面板和生成提示词。

学习模式下增加：

- `硬件提问` 主按钮。
- `解释选区`、`追踪信号`、`解释器件`、`分析电源` 快捷按钮。
- 学习级别：入门、进阶、深入。
- 证据来源标识：离线图片、EasyEDA 当前页已验证、数据手册。
- 状态提示：选区不足、证据读取中、页面已变化、回答完成。

### 6.2 `LearningCanvasAdapter`

职责：

- 从 JLC Hardware Learning 选区构造 `CanvasSelectionEnvelope`。
- 校验至少存在一张源图片、一个可解释图形或明确文本对象。
- 生成确定性选区截图并计算 SHA-256。
- 将自然语言问题分类到已知意图；分类不确定时使用 `explain-selection`。
- 绑定当前学习会话和可选 EasyEDA 上下文。
- 控制超时、取消、去重和幂等键。

建议 TypeScript 接口：

```typescript
interface LearningCanvasAdapter {
  captureSelection(input: CaptureSelectionInput): Promise<CanvasSelectionEnvelope>;
  createQuestion(input: CreateLearningQuestionInput): Promise<LearningQuestion>;
  resolveIntent(question: string, quickAction?: LearningIntent): LearningIntent;
  validateQuestion(question: LearningQuestion): ValidationResult;
}
```

适配器不能：

- 调用 `eda.*`。
- 搜索器件库或数据手册。
- 构造硬件结论。
- 直接改写整个 JLC Hardware Learning snapshot。

### 6.3 `OfficialEasyedaEvidenceProvider`

职责：

- 从 `api-manifest.json` 查询准确方法签名。
- 从 `jlc-hardware-learning-api-map.json` 选择只读方法。
- 检查 Bridge 服务身份和目标 EasyEDA 窗口。
- 在读取前后冻结并复核工程和页面身份。
- 按意图收集最少证据，并标准化为 `EvidenceBundle`。
- 对每个证据项计算哈希、记录来源和范围。

建议接口：

```typescript
interface OfficialEasyedaEvidenceProvider {
  probe(): Promise<EasyedaBridgeStatus>;
  freezeIdentity(): Promise<IdentitySnapshot>;
  collect(request: EvidenceRequest, signal?: AbortSignal): Promise<EvidenceBundle>;
  verifyIdentity(before: IdentitySnapshot): Promise<IdentityVerification>;
}
```

硬限制：

- 只允许 API Map 中 `access=read` 的方法。
- 不允许使用 `@internal` 方法。
- 不允许 `openProject`、`openDocument`、页面切换、保存、修改或创建。
- `SCH_PrimitiveComponent.getAll` 的 `allSchematicPages` 固定为 `false`。
- 页面 UUID 在读取前后变化时，证据包标记为 `stale` 并停止回答事实性结论。
- JLC Hardware Learning 图片无法证明与当前 EasyEDA 页面相同时，不使用区域坐标直接查询图元。

### 6.4 `EvidenceNormalizer`

将不同证据转成统一图模型：

```text
ComponentNode
  id, designator, name, value, manufacturer, partNumber, position

PinNode
  componentId, pinNumber, pinName, pinType, netName

NetNode
  name, labels, powerRole, connectedPins

WireEdge
  primitiveId, points, netName

VisualRegion
  sourceAsset, canvasBounds, optionalEasyedaBounds
```

归一化阶段只做结构转换和显式标注，不推断电路功能。对于同名网络、空网络名、重复位号或未知引脚，原样保留并产生 warning。

### 6.5 `HardwareTutorEngine`

职责：

- 根据意图选择问题分析器。
- 将图像信息和结构化 EasyEDA 证据合并。
- 生成适配学习级别的解释。
- 把每条事实性结论绑定到证据 ID。
- 将不确定推断放入 `assumptions`，缺失信息放入 `unknowns`。
- 检查高压、功率、极性、热、额定值等安全提示。

建议内部模块：

```text
QuestionRouter
SelectionExplainer
SignalTraceAnalyzer
ComponentExplainer
PowerPathAnalyzer
ConceptReviewAnalyzer
OptionComparisonAnalyzer
ClaimEvidenceBinder
SafetyNoteEngine
LearningLevelFormatter
```

第一版不需要建立通用电路求解器。每个分析器只输出证据能够支撑的拓扑和概念说明。

### 6.6 `CanvasAnswerPresenter`

职责：

- 在 Codex 对话中完整展示 `TutorAnswer`。
- 可选地将短答案写成 JLC Hardware Learning 普通便签。
- 将关键器件或路径以矩形、高亮和箭头标记。
- 使用 `operationId` 保证重复请求不会插入两套答案。

只接受四种命令：

```text
note
highlight
rectangle
arrow
```

不得接受或降级生成以下内容：

```text
image
html
embed
slides
video
```

### 6.7 `LearningSessionStore`

职责：

- 保存会话、问题、证据、答案和画板命令审计记录。
- 使用内容哈希去重证据。
- 支持从问题跳回 JLC Hardware Learning shape ID 和 EasyEDA 页面 UUID。
- 支持数据契约升级和回滚。

它不保存 EasyEDA 登录信息、Bridge token 或外部 API 凭据。

## 7. UI 设计

### 7.1 画板布局

```text
┌──────────────────────────────────────────────────────────────────┐
│ 硬件学习  [离线图片/当前页已验证] [入门 v]              [退出] │
├──────────────────────────────────────────────────────────────────┤
│ 选择 手型 导入图片 画笔 文字 箭头 便签 矩形 高亮  硬件提问     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│       ┌──────────── 原理图图片 ────────────┐                     │
│       │                                     │                     │
│       │     ┌──── 用户框选区域 ────┐        │                     │
│       │     │ U3 + R12/R13         │ ───▶  为什么这样反馈？      │
│       │     └──────────────────────┘        │                     │
│       └─────────────────────────────────────┘                     │
│                                             ┌──────────────────┐ │
│                                             │ 回答便签（可选） │ │
│                                             └──────────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│ [解释选区] [追踪信号] [解释器件] [分析电源]  问题输入… [发送] │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 提问面板

字段：

- `问题`：必填，1-4000 字符。
- `意图`：默认自动，可由快捷按钮固定。
- `学习级别`：入门、进阶、深入。
- `证据模式`：仅画板、结合 EasyEDA 当前页。
- `回答回写画板`：默认开启；MVP 阶段不可用时显示“仅在 Codex 回答”。

发送前校验：

- 选区为空：阻止发送。
- 只选中箭头或空文本：提示选择源图片或电路对象。
- 选择多张图片：允许，但要求明确主图，最多四张。
- 选区截图大于限制：等比缩小，保留原始资产引用和哈希。
- EasyEDA 模式但 Bridge 不可用：允许降级到离线图片，必须明确告知。

### 7.3 回答呈现

Codex 中完整回答建议按以下顺序：

1. 一句话结论。
2. 电路如何工作。
3. 关键器件/网络。
4. 证据依据。
5. 假设和未知项。
6. 安全或设计风险。
7. 建议继续追问。

画板便签只保留一句话结论和 2-4 个关键点，避免遮挡原理图。详细证据始终留在 Codex 和本地学习记录中。

## 8. 关键交互流程

### 8.1 离线图片提问

```text
用户导入图片
  -> JLC Hardware Learning 保存 page-local asset
  -> 用户框选并提问
  -> Widget 生成选区截图和 SelectionEnvelope
  -> LearningCanvasAdapter 构造 LearningQuestion(mode=offline-artifact)
  -> HardwareTutorEngine 基于图片和标注回答
  -> Presenter 返回 Codex 答案并插入普通便签
```

回答必须标明“仅依据图片，未读取 EasyEDA 结构化数据”。

### 8.2 结合当前 EasyEDA 页面提问

```text
LearningQuestion
  -> Bridge health + service identity
  -> freezeIdentity(before)
  -> 验证 SCHEMATIC_PAGE
  -> 按意图最小化读取图元/网络
  -> freezeIdentity(after)
  -> before == after ? EvidenceBundle.verified : EvidenceBundle.stale
  -> HardwareTutorEngine
  -> TutorAnswer
```

证据采集期间不自动切换页面。若当前 EasyEDA 页面不是用户画板图片对应页面，提示用户打开正确页面后重新提问。

### 8.3 继续追问

继续追问必须复用 `sessionId` 并新建 `questionId`。旧证据只有在以下条件同时满足时才能复用：

- JLC Hardware Learning 源图片 SHA-256 未变化。
- 选区引用的 shape 仍存在。
- EasyEDA project UUID 和 document UUID 未变化。
- 证据 TTL 未过期或用户明确接受历史快照。

否则重新采集证据。

## 9. 状态机

```text
IDLE
  -> SELECTING
  -> COMPOSING
  -> VALIDATING
  -> CAPTURING_SELECTION
  -> FREEZING_IDENTITY
  -> COLLECTING_EVIDENCE
  -> VERIFYING_IDENTITY
  -> ANSWERING
  -> PRESENTING
  -> COMPLETE
```

可恢复错误状态：

| 错误码 | 含义 | 恢复方式 |
|---|---|---|
| `NEEDS_SELECTION` | 没有可解释选区 | 回到画板选择 |
| `NEEDS_SOURCE_ASSET` | 只有标注，没有原始图或结构化对象 | 选择原理图图片 |
| `BRIDGE_UNAVAILABLE` | EasyEDA Bridge 不可用 | 降级离线或重连 |
| `WRONG_DOCUMENT_TYPE` | 当前不是原理图页 | 用户手动打开正确页面 |
| `STALE_EASYEDA_CONTEXT` | 读取过程中页面变化 | 丢弃本轮实时证据并重试 |
| `REGION_NOT_CALIBRATED` | 画板坐标不能映射 EasyEDA 坐标 | 使用整页证据或重新导入验证导出 |
| `EVIDENCE_PARTIAL` | 部分 API 无数据或受权限限制 | 带 warning 回答，不补猜 |
| `ANSWER_PRESENTATION_FAILED` | 画板便签写入失败 | Codex 答案仍视为成功 |
| `CANCELLED` | 用户取消 | 不保存未完成答案 |

## 10. 选区与截图算法

### 10.1 选区归一化

JLC Hardware Learning 当前持久化选区包含 shape、props、asset 等信息，但没有保证提供准确的页面世界坐标。学习适配补丁必须使用 tldraw Editor 在 Widget 内计算：

- `shapePageBounds`：每个 shape 的页面坐标边界。
- `shapePageTransform`：包含父级、旋转和缩放后的变换。
- `unionBounds`：所有选中对象的联合边界。
- `sourceImageShapes`：与联合边界相交的图片对象。
- `annotationShapes`：框、箭头、画笔、文本和高亮。

不能用 snapshot 中的原始 `x/y` 直接替代页面坐标。

### 10.2 截图生成

截图是 JLC Hardware Learning 对既有画板内容的确定性渲染，不调用任何生成模型：

1. 以 `unionBounds` 为基础增加 24-48 像素边距。
2. 包含源图片和用户标注。
3. 最大边长默认 4096 像素，超过后等比缩放。
4. PNG 保存到当前 JLC Hardware Learning 页的 `assets/learning/`。
5. 计算文件 SHA-256 并写入 `CanvasSelectionEnvelope`。
6. 保留原始图片 asset URL，不覆盖、不替换、不删除原图。

### 10.3 EasyEDA 坐标校准

只有满足以下条件才允许调用 `sch_Document.getPrimitivesInRegion`：

- 图片来自同一 document UUID 的验证导出。
- 当前安装配置不允许直接调用已知会卡页的 `Current Schematic Page` 视觉导出；图片必须是已有的同页验证产物，或范围为 `Current Schematic` 且有可核验的单页证明。
- 记录导出尺寸、边距、方向和 EasyEDA 页面数据边界。
- 存在可验证的二维仿射变换：`easyedaPoint = M × imagePoint`。
- 至少用两个已知图元位置复核误差；误差超过阈值则放弃区域 API。

未校准时，使用图像选区识别出的位号/网络名去过滤整页结构化证据，不猜坐标映射。

## 11. EasyEDA 证据读取设计

所有方法均来自固定 API manifest，完整机器路由见 [`../manifests/jlc-hardware-learning-api-map.json`](../manifests/jlc-hardware-learning-api-map.json)。

### 11.1 身份门禁

每次实时问题必须调用：

- `eda.dmt_Project.getCurrentProjectInfo()`。
- `eda.dmt_SelectControl.getCurrentDocumentInfo()`。
- `eda.dmt_Schematic.getCurrentSchematicPageInfo()`。

要求：

- project UUID 非空。
- document UUID 非空。
- `documentType === EDMT_EditorDocumentType.SCHEMATIC_PAGE`。
- schematic page UUID 与 document UUID 的关系可解释。
- 读取结束后再次执行相同检查。

### 11.2 最小证据级别

| 级别 | 数据 | 使用条件 |
|---|---|---|
| E0 | JLC Hardware Learning 选区截图和标注 | 所有问题 |
| E1 | 当前工程/页面身份 | 使用实时 EasyEDA 时必需 |
| E2 | 当前页器件、导线、网络 | 大多数解释与信号追踪 |
| E3 | 引脚、属性、单个网络、器件库详情 | 问题明确指向器件或网络 |
| E4 | 网表、当前页 PNG/SVG/PDF | E2/E3 不能充分解释时 |

不得因为 API 可用就默认采集 E4。

画板 PNG 由隔离的 `EasyedaExportAdapter` 通过已验证的官方 `Current Schematic` PNG 能力生成，导出前后和插入前均复核身份。该兼容适配器是唯一允许使用官方旧视觉导出方法的边界，普通 API 计划仍拒绝 deprecated 方法；画板层不得直接构造导出、本地文件保存或 EasyEDA 调用。`Current Schematic` 不得冒充精确当前图页，EPRO 衍生图像和全工程图页渲染均禁止进入画板。

### 11.3 按意图路由

| 意图 | 核心数据 | 条件数据 |
|---|---|---|
| `explain-selection` | 当前页器件、导线、网络 | 区域图元、当前页导出 |
| `trace-signal` | 器件、引脚、导线、网络 | 单个网络、Protel2 网表 |
| `explain-component` | 指定器件、引脚、属性 | 器件库详情 |
| `power-path` | 器件、引脚、导线、网络 | 网表 |
| `review-concept` | 器件、导线、网络 | 引脚、网表、当前页导出 |
| `compare-options` | 指定器件与属性 | 器件库、外部官方数据手册 |

### 11.4 证据一致性

`EvidenceBundle.status`：

- `verified`：前后身份一致且必需证据完整。
- `partial`：身份一致，但部分 API 无结果或权限受限。
- `stale`：前后身份不一致；不得输出依赖实时结构的确定性结论。
- `offline`：只使用 JLC Hardware Learning/用户文件。

## 12. 硬件导师分析设计

### 12.1 问题路由

优先级：

1. 用户点击的快捷意图。
2. 问题中的显式动作词和对象。
3. 选区内容特征。
4. 默认 `explain-selection`。

一次问题只选择一个主意图，可以追加辅助分析器，但不能并行生成互相矛盾的答案。

### 12.2 图结构

信号追踪构建有向/无向混合图：

- 网络连接关系先作为无向边。
- 根据引脚类型、器件类别和明确的 IN/OUT 标记增加方向提示。
- 电源和地网络标记特殊角色。
- 方向不确定时保留双向并在答案中说明。

不能仅根据网络名称猜模拟/数字方向，也不能把相交线条直接视为连接，必须依赖 EasyEDA 网络或节点证据。

### 12.3 学习级别

| 级别 | 表达策略 |
|---|---|
| 入门 | 先说明作用，再解释每个器件；减少公式 |
| 进阶 | 增加信号流、关键公式、设计权衡 |
| 深入 | 增加边界条件、误差来源、稳定性和额定值检查 |

不同级别只能改变解释深度，不能改变证据标准。

### 12.4 证据绑定

每个事实性 claim 至少引用一个 `evidenceId`。以下内容不能放进 claim：

- 未经数据手册确认的器件绝对最大额定值。
- 仅凭图片猜测的内部芯片功能。
- 没有网络证据支持的连接关系。
- 没有 BOM/供应商证据支持的库存、价格或可采购性。

这些内容只能进入 `assumptions` 或 `unknowns`。

## 13. 数据契约

正式 JSON Schema 位于 [`../contracts/learning-canvas-contracts.schema.json`](../contracts/learning-canvas-contracts.schema.json)。核心对象：

端到端示例位于 [`../contracts/examples/learning-question.example.json`](../contracts/examples/learning-question.example.json)、[`../contracts/examples/evidence-bundle.example.json`](../contracts/examples/evidence-bundle.example.json) 和 [`../contracts/examples/tutor-answer.example.json`](../contracts/examples/tutor-answer.example.json)。

| 对象 | 生产者 | 消费者 |
|---|---|---|
| `CanvasSelectionEnvelope` | JLC Hardware LearningLearningUI | LearningCanvasAdapter |
| `LearningQuestion` | LearningCanvasAdapter | EvidenceProvider / TutorEngine |
| `EvidenceBundle` | OfficialEasyedaEvidenceProvider | HardwareTutorEngine |
| `TutorAnswer` | HardwareTutorEngine | CanvasAnswerPresenter |
| `CanvasAnnotationCommand` | HardwareTutorEngine | CanvasAnswerPresenter |
| `LearningSession` | LearningSessionStore | 全模块 |

所有对象带独立 `schemaVersion`。破坏性字段变更必须提升大版本并提供迁移器。

## 14. JLC Hardware Learning 最小补丁设计

### 14.1 向后兼容参数

扩展 `render_hardware_learning_canvas_widget`：

```json
{
  "projectDir": "D:/project",
  "mode": "hardware-learning",
  "analyticsEnabled": false
}
```

省略 `mode` 时保持 JLC Hardware Learning 默认行为，避免影响普通用户。

### 14.2 建议新增源码目录

```text
src/learning/
  hardwareLearningProfile.js
  HardwareQuestionPanel.jsx
  captureLearningSelection.js
  learningMessage.js

mcp/learning/
  save-learning-question.mjs
  insert-learning-annotations.mjs
```

JLC Hardware Learning 原有图片生成模块不被学习代码 import。

### 14.3 建议新增 MCP 工具

`save_hardware_learning_question`：

- 调用方：Widget。
- 输入：问题元数据、SelectionEnvelope、选区截图数据。
- 输出：本地 question 路径、截图 asset URL、哈希。
- 权限：本地写、非破坏、幂等。

`insert_hardware_learning_annotations`：

- 调用方：模型或 Widget。
- 输入：`operationId` 和 `CanvasAnnotationCommand[]`。
- 只允许 note/highlight/rectangle/arrow。
- 禁止 asset、image、embed、HTML 记录。
- 同一 `operationId` 重放时返回原结果。

### 14.4 遥测禁用

JLC Hardware Learning 当前源码默认初始化 Google Analytics，并可通过 `track_hardware_learning_analytics_event` 发送事件。学习模式必须在初始化之前短路：

```text
mode == hardware-learning
  => analyticsEnabled = false
  => 不加载 Google tag
  => 不创建 analytics client ID
  => 不调用 track_hardware_learning_analytics_event
  => CSP 不需要 analytics domains
```

只在编排器中“不主动调用分析工具”是不够的，必须阻止 Widget 自身初始化。

## 15. 存储设计

JLC Hardware Learning 继续保存自己的画布：

```text
<projectDir>/canvas/pages/<page-id>/hardware-learning-canvas.json
<projectDir>/canvas/pages/<page-id>/assets/
```

学习业务数据单独保存：

```text
<projectDir>/.easyeda-hardware-workbench/learning/
  sessions/<session-id>/session.json
  questions/<question-id>.json
  evidence/<sha256>.json
  answers/<answer-id>.json
  operations/<operation-id>.json
  assets/<sha256>.<ext>
  schema-version.json
```

存储规则：

- 文件名使用内部 ID 或内容哈希，不使用用户问题全文。
- JLC Hardware Learning 资产优先保存相对路径和哈希，不重复复制大文件。
- EasyEDA API 原始结果在写入前去除无关字段和潜在凭据。
- 完成写入采用临时文件 + 原子替换。
- 会话删除只删除 Workbench 学习记录，不删除 JLC Hardware Learning 原图。

## 16. 安全与权限

### 16.1 四层禁用生图

1. UI：隐藏所有生成入口。
2. Skill：只暴露 `jlc-hardware-learning`，拒绝 `imagegen` 等生成式图片能力。
3. MCP：学习编排器只允许固定工具白名单。
4. Contract：`CanvasAnnotationCommand.kind` 不存在 image/html/embed/slides。

任一层收到生图请求都返回 `CAPABILITY_DISABLED_IN_HARDWARE_LEARNING_MODE`。

### 16.2 EasyEDA 写入隔离

- API Map 中全部方法必须为 read。
- Bridge 代码生成器检查方法 ID、release tag 和访问策略。
- 学习模式没有写入授权升级路径；用户提出“帮我改”时必须退出学习流程，交给未来设计修改模块重新确认。
- JLC Hardware Learning 的形状写入只影响本地画板，不影响 EasyEDA。

### 16.3 隐私

- 学习模式禁用 JLC Hardware Learning 遥测和外部分析域名。
- 原理图截图、问题、选区和答案默认保存在本地项目。
- 外部数据手册搜索必须显式进入 Datasheet Provider，并记录请求来源。
- 日志不记录图片 Base64、完整问题内容或 EasyEDA Bridge token。

## 17. 并发、取消与幂等

- 每个问题分配唯一 `questionId`。
- 同一画板页最多一个 `COLLECTING_EVIDENCE` 或 `PRESENTING` 操作。
- 新问题可以取消旧问题；已完成证据文件保留但标记 orphan，后续清理。
- Widget 关闭时中止截图上传和未完成消息，但不取消已经开始的只读 EasyEDA API 请求；请求结束后结果不呈现并标记 cancelled。
- 画板回写使用 `operationId`，重复调用不得新增重复便签。
- EvidenceBundle 使用身份 + 请求参数 + payload 的规范化哈希去重。

## 18. 错误处理与降级

| 场景 | 行为 |
|---|---|
| JLC Hardware Learning MCP 不可用 | 保留问题草稿，提示修复插件，不读取画板文件绕过 MCP |
| EasyEDA Bridge 不可用 | 用户可选择离线回答 |
| 多个 EasyEDA 窗口 | 首次实时读取时要求明确活动窗口 |
| 页面在采集中切换 | 丢弃实时证据并标记 stale |
| API 不在 manifest | 停止该证据路径，不猜方法 |
| beta API 返回空 | 记录 warning，尝试更低级别证据，不使用内部 API |
| 选区截图失败 | 仍保存问题草稿，不发送不完整上下文 |
| 画板回写失败 | Codex 回答保持成功，提供重试回写 |
| 回答证据不足 | 明确 unknowns，建议用户补选区或打开正确页面 |

## 19. 可观测性

只记录本地结构化事件：

```text
learning.question.created
learning.selection.captured
learning.easyeda.identity_frozen
learning.evidence.collected
learning.evidence.stale
learning.answer.created
learning.canvas.presented
learning.operation.failed
```

每条事件只包含：ID、状态、耗时、数量、错误码和版本，不包含图片、问题全文或电路内容。日志默认位于 Workbench 本地目录，不上传。

关键指标：

- 问题完成率。
- Bridge 降级率。
- stale identity 次数。
- 证据完整度。
- 回写幂等冲突次数。
- 每个意图的平均证据调用数。

## 20. 代码组织建议

```text
HeiWuEDA/
  skill/
    SKILL.md
    references/
      learning-mode.md

  packages/
    learning-contracts/
    jlc-hardware-learning-adapter/
    easyeda-evidence-provider/
    hardware-tutor-core/
    learning-session-store/

  integrations/
    jlc-hardware-learning-plugin/
      .codex-plugin/plugin.json
      skills/jlc-hardware-learning/
      mcp/generated/

  tests/
    contracts/
    fixtures/
    integration/
    live-readonly/

  materials/
    manifests/
    contracts/
    references/
```

融合 Skill 的 `SKILL.md` 只保留模式选择和关键门禁；本详细设计、API Map 和 Contract 通过 references 按需读取，避免把所有细节加载到每次任务。

## 21. 测试设计

### 21.1 Contract 测试

- 四类主要对象能通过 JSON Schema。
- 缺少 UUID、hash、question 或 evidence 引用时拒绝。
- `CanvasAnnotationCommand` 拒绝 image/html/embed/slides。
- 未知 schemaVersion 拒绝。

### 21.2 JLC Hardware Learning Adapter 测试

- 旋转、分组、Frame 嵌套后的 page bounds 正确。
- 多选图片与标注的 union bounds 正确。
- 截图不改变原 shape 和 asset。
- hardware-learning 模式不渲染四类生成入口。
- hardware-learning 模式不加载 Google tag、不调用 analytics MCP。
- 重复 operationId 不插入重复答案。

### 21.3 API Registry 测试

- API Map 的每个 runtime module/class/method 均存在于 0.4.15 manifest。
- 所有方法 access 均为 read。
- 不引用 `@internal` 或 unknown method。
- 枚举参数使用枚举成员名称。
- `allSchematicPages` 保持 false。

### 21.4 Evidence Provider 测试

- before/after 身份一致得到 verified。
- document UUID 变化得到 stale。
- 非原理图文档得到 WRONG_DOCUMENT_TYPE。
- Bridge 断开可降级 offline。
- 同名位号跨页不被合并。

### 21.5 Tutor 测试

- 每个事实 claim 都有 evidenceId。
- 没有证据的内容只能进入 assumptions/unknowns。
- 三种学习级别不改变事实结论。
- 高压/功率/极性样例产生 safetyNotes。
- 图像与结构化网络冲突时优先结构化证据并提示冲突。

### 21.6 端到端验收

至少准备六个固定 fixture：

1. 运放反相放大器。
2. RC 低通滤波器。
3. LDO 电源和去耦。
4. MCU UART 接口。
5. 差分信号链。
6. 有意制造的图片/网表冲突样例。

真实 EasyEDA 验收只读，不保存工程，并记录工程 UUID、页面 UUID、输入快照和输出证据哈希。

另外必须覆盖 Widget 原生记录入口：保存的 PNG 在回答前复核 SHA-256；
同一 `questionId` 重放时复用相同 evidence/answer/operation/command ID；同页
继续追问在重开进程后能恢复有序历史；跨 JLC Hardware Learning 页复用同一 session 必须阻断。

## 22. 分阶段实施

### M0：设计基线

交付：

- 本详细设计。
- JSON Contract。
- API Map。
- JLC Hardware Learning/EasyEDA 版本锁和验证器。

完成门槛：所有机器文件可解析，API Map 全量映射成功。

### M1：离线 MVP

交付：

- 使用现有 JLC Hardware Learning 选区和图片。
- 在 Codex 中触发“解析 JLC Hardware Learning 选区”。
- 构造 LearningQuestion 和 TutorAnswer。
- 仅在 Codex 中回答。

完成门槛：不改 JLC Hardware Learning 上游、不连接 EasyEDA，也能完成六个 fixture 的图片问答。

### M2：实时只读证据

交付：

- Bridge probe 和身份冻结。
- 当前页器件/导线/网络证据。
- EvidenceBundle 和 stale 检测。

完成门槛：页面切换测试不能产生混页结论。

### M3：JLC Hardware Learning 学习模式补丁

交付：

- `mode=hardware-learning`。
- 隐藏生成入口。
- 禁用遥测。
- 硬件提问面板与选区截图。
- 两个学习 MCP 工具。

完成门槛：UI、MCP、Contract 三层均无法插入生成内容。

### M4：画板回答与课程化

交付：

- 便签、高亮、箭头回写。
- 继续追问和会话恢复。
- 三种学习级别。
- 本地学习历史。
- Widget 保存问题的自动导入、截图校验、回答持久化与 `learning-resume` 恢复。

完成门槛：重复请求幂等，关闭/重开 Widget 后会话可恢复。

## 23. 首版验收标准

首版可以称为“学习画板可用”必须同时满足：

- 用户能选择一张原理图图片和标注后提交问题。
- 能返回结构化回答，并明确证据、假设和未知项。
- 实时模式绑定 project UUID 和 document UUID。
- 页面切换会中止事实性回答。
- 所有 EasyEDA API 调用都能映射到固定 manifest。
- JLC Hardware Learning 生图、改图、AI HTML 和 Slides 均不可触发。
- JLC Hardware Learning 遥测在学习模式关闭。
- 回写只产生 note/highlight/rectangle/arrow。
- 所有用户材料默认保存在本地项目。
- 六个固定 fixture 和至少一个真实只读 EasyEDA 页面验收通过。

## 24. 实施前置事项

1. 本机 JLC Hardware Learning 0.1.2 与设计基线 0.1.27 存在版本差异；开发前先建立升级回滚包。
2. 活动实现只在独立的 `jlc-hardware-learning` 源码与发布包中维护；第三方快照只作许可证归档和迁移测试依据。
3. 先完成 M1 合同和 fixture，再连接真实 EasyEDA。
4. 真实页面验收必须保持只读，且每次重新确认 project/document UUID。
