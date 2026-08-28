# JLC Hardware Learning 硬件学习画板架构

## 定位

JLC Hardware Learning 只作为 `黑五EDA` 的学习交互界面：用户把原理图截图、官方导出证据或数据手册图片放入无限画布，用矩形、箭头、自由笔和文字框出问题区域，再让硬件导师解释。

这里明确不使用 JLC Hardware Learning 的生图、按标注改图、AI HTML 或 AI Slides 功能。JLC Hardware Learning 也不是 EasyEDA API 的来源，不能定义、猜测或直接调用 `eda.*` 接口。

当前固定快照、提交和许可证见 [`../manifests/integrations.lock.json`](../manifests/integrations.lock.json)，可执行策略见 [`../manifests/jlc-hardware-learning-profile.json`](../manifests/jlc-hardware-learning-profile.json)。

可直接进入开发的模块接口、UI、状态机、存储、测试和里程碑见 [`jlc-hardware-learning-detailed-design.md`](jlc-hardware-learning-detailed-design.md)。

## 分层

```text
JLC Hardware LearningLearningUI
  ├─ 专用 SVG 画布、原理图图片、学习框、箭头、文字、当前选区
  └─ 通过 Codex 正常对话栏提出问题
                 │ LearningQuestion
                 ▼
LearningCanvasAdapter
  ├─ 读取 get_hardware_learning_selection / get_hardware_learning_canvas_state
  ├─ 解析 shape、bounds、asset 和用户问题
  └─ 生成 SelectionEnvelope，不接触 eda.*
                 │ EvidenceRequest
                 ▼
OfficialEasyedaEvidenceProvider
  ├─ 只查 api-manifest.json 中存在的官方 API
  ├─ 默认只读，绑定 projectUuid + documentUuid + documentType
  └─ 返回原理图、器件、网络、BOM 或导出证据快照
                 │ LearningContext
                 ▼
HardwareTutorEngine
  ├─ 电源、信号链、接口、器件、拓扑和 BOM 解释
  ├─ 区分证据、推断、未知项与安全提示
  └─ 输出 TutorAnswer；不调用任何生图能力
                 │
                 ├─ MVP：Codex 对话中回答
                 └─ Adapter：普通文本便签、框和箭头写回 JLC Hardware Learning
```

这个分层让 JLC Hardware Learning 可以升级或替换，而 EasyEDA API、设计审查和 BOM 模块不需要跟着改动。

## 模块边界

### `JLC Hardware LearningLearningUI`

负责：

- 打开不依赖 tldraw 前端运行时的专用硬件学习 Widget。
- 保存项目内画布、页面、选区和视图状态。
- 导入用户图片、EasyEDA 官方导出截图和数据手册证据。
- 让用户通过矩形、箭头、自由笔、文本和多选表达问题范围。

不负责：

- 生成或修改图片。
- 生成 HTML、Slides 或视觉成品。
- 读取或写入 EasyEDA 工程。
- 判断电气设计是否正确。

### `LearningCanvasAdapter`

这是融合 Skill 自己维护的薄适配层，不应把业务逻辑写进 JLC Hardware Learning 源码。

输入 `LearningQuestion`：

```json
{
  "questionId": "question:<uuid>",
  "sessionId": "learning:<uuid>",
  "question": "这个框里的运放为什么需要这两个电阻？",
  "intent": "explain-selection",
  "selection": {
    "pageId": "page:<id>",
    "shapeIds": ["shape:<id>"],
    "assetRefs": ["/page-assets/<page>/<file>"],
    "bounds": { "x": 0, "y": 0, "w": 100, "h": 80 }
  },
  "easyedaContextRef": {
    "projectUuid": "<uuid>",
    "documentUuid": "<uuid>",
    "documentType": "SCHEMATIC_PAGE",
    "capturedAt": "<ISO-8601>"
  }
}
```

适配器必须保留 JLC Hardware Learning 的 shape ID 和 EasyEDA 的 document UUID，不能只靠标题、图片文件名或当前标签页猜上下文。

### `OfficialEasyedaEvidenceProvider`

只通过融合 Skill 的 EasyEDA API Registry 工作：

- 签名从 [`../manifests/api-manifest.json`](../manifests/api-manifest.json) 查询。
- 示例从 [`../manifests/api-example-index.json`](../manifests/api-example-index.json) 追溯。
- 每次读取记录工程 UUID、页面 UUID、文档类型和采集时间。
- JLC Hardware Learning 只能收到归一化证据，不持有 Bridge 连接，也不能提交 `eda.*` 代码。
- 学习模式默认只读；用户在画板上的“修改建议”不等于授权写回 EasyEDA。

建议的证据类型：

```text
SchematicImageEvidence
SchematicPrimitiveEvidence
NetTopologyEvidence
ComponentPropertyEvidence
BomLineEvidence
DatasheetEvidence
```

### `HardwareTutorEngine`

第一批问题路由：

| 路由 | 典型问题 | 优先证据 |
|---|---|---|
| `explain-selection` | 框里的电路在做什么 | 图片选区、图元、网络 |
| `trace-signal` | 信号从哪里来、到哪里去 | 网表、网络标签、器件引脚 |
| `explain-component` | 这个芯片/阻容为什么这样选 | 器件属性、数据手册、BOM |
| `power-path` | 电源如何变换和分配 | 电源网络、稳压器、去耦 |
| `review-concept` | 这样设计可能有什么问题 | 原理图证据、规则和明确假设 |
| `compare-options` | 两种方案有什么区别 | 模块规格、BOM、约束条件 |

输出统一为 `TutorAnswer`：

```json
{
  "answer": "面向学习者的解释",
  "evidence": [
    { "source": "easyeda", "ref": "documentUuid/net/ref", "claim": "证据支持的结论" }
  ],
  "assumptions": ["根据图片或上下文作出的推断"],
  "unknowns": ["当前证据无法确认的事项"],
  "safetyNotes": ["高压、功率、极性或器件额定值提示"],
  "canvasAnnotations": [
    { "kind": "note", "anchorShapeId": "shape:<id>", "text": "简短说明" }
  ]
}
```

`canvasAnnotations` 只允许普通文本、矩形、高亮和箭头；不得包含生成图片或 HTML。

## JLC Hardware Learning 工具策略

当前 JLC Hardware Learning 0.1.27 硬件学习 overlay 已验证暴露 15 个工具。学习模式按三组使用：

### 模型可主动调用

- `render_hardware_learning_canvas_widget`
- `get_hardware_learning_canvas_state`
- `get_hardware_learning_selection`
- `read_hardware_learning_page_asset`
- `save_hardware_learning_question`
- `insert_hardware_learning_annotations`

### 仅用于画板自身持久化

- `save_hardware_learning_canvas_state`
- `save_hardware_learning_selection_state`
- `save_hardware_learning_view_state`
- `save_hardware_learning_reference_image`

### 仅由 Widget 调用的本地导出能力

- `download_hardware_learning_file`
- `copy_hardware_learning_image_to_clipboard`

这些能力支持图页 PNG/SVG、选区裁切 PNG、剪贴板和 JSON 备份；不授权 EasyEDA 导出或写入。

### 学习编排器不调用

- `insert_hardware_learning_html_draft`
- `track_hardware_learning_analytics_event`

`insert_hardware_learning_image` 只有在放置用户图片、EasyEDA 官方导出或带来源的数据手册图片时才能使用，并强制 `replaceAiImageHolder=false`。它不能接收任何生成图片。

## 当前实现

学习 overlay 已完成专用 React + SVG Widget、显式学习框、selection v2、最后一次非空选择、问题持久化和幂等教学标注。生成 Widget 不包含 tldraw UI 或授权水印字符串，但继续使用原 JLC Hardware Learning snapshot 作为数据兼容格式。前端已复刻原 JLC Hardware Learning 的四区布局、样式面板、几何工具、橡皮擦、框选多选、复制、缩放菜单和小地图，同时保持原理图底图不可破坏。用户通过 Codex 正常对话栏提问，不再使用画布内的提问/导入面板。

发布以独立的 `jlc-hardware-learning` 插件包维护。前端工具、纯几何、教学标注、导出和 MCP 存储已经拆成模块；生命周期推理、EasyEDA 官方证据和 BOM 逻辑仍在工作台层。详细结构、迁移和测试矩阵见 [`jlc-hardware-learning-detailed-design.md`](jlc-hardware-learning-detailed-design.md)。

## 版本与迁移注意

当前上游快照为 JLC Hardware Learning 0.1.27。硬件学习版作为独立 personal plugin 安装，Marketplace cache 只承载构建产物，不能直接修改；源码、补丁、生成物和安装版本必须分别校验。每次升级均需重放 12 个补丁、运行完整质量链、更新 cachebuster，并保留 Git bundle 回滚备份。
