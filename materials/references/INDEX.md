# EasyEDA 官方 API 资料索引

本目录是 `easyeda-hardware-workbench` 的第一阶段资料包，只整理公开资料、版本和示例，不连接或修改 EasyEDA 工程。

## 当前快照

- 官方类型定义：`@jlceda/pro-api-types` 0.4.15。
- 官方 `easyeda-api-skill` 快照：1.1.22。
- 本机已安装 `easyeda-api-skill`：1.1.3；当前只记录差异，不自动升级。
- 类型定义规模：127 个类、73 个枚举、122 个接口、24 个类型别名。
- 本地官方教程快照：13 页。
- 本地 Git 快照：4 个核心仓库、10 个专题示例仓库。

精确版本、提交和文件哈希见 [`../manifests/sources.lock.json`](../manifests/sources.lock.json)。官方仓库总目录见 [`../manifests/official-repository-catalog.json`](../manifests/official-repository-catalog.json)。

机器可读 API 清单见 [`../manifests/api-manifest.json`](../manifests/api-manifest.json)，官方方法级调用索引见 [`../manifests/api-example-index.json`](../manifests/api-example-index.json)，覆盖率摘要见 [`api-index-summary.md`](api-index-summary.md)。

硬件学习画板采用固定 JLC Hardware Learning 快照，版本锁见 [`../manifests/integrations.lock.json`](../manifests/integrations.lock.json)，禁用生图的学习配置见 [`../manifests/jlc-hardware-learning-profile.json`](../manifests/jlc-hardware-learning-profile.json)，模块设计见 [`learning-canvas-architecture.md`](learning-canvas-architecture.md)。

学习画板的详细开发规格见 [`jlc-hardware-learning-detailed-design.md`](jlc-hardware-learning-detailed-design.md)，数据契约见 [`../contracts/learning-canvas-contracts.schema.json`](../contracts/learning-canvas-contracts.schema.json)，官方只读 API 路由见 [`../manifests/jlc-hardware-learning-api-map.json`](../manifests/jlc-hardware-learning-api-map.json)。

JLC Hardware Learning 的专用 SVG 运行时、显式学习框、旧数据迁移、选择契约、导出防卡死约束、测试矩阵和后续扩展点已并入 [`jlc-hardware-learning-detailed-design.md`](jlc-hardware-learning-detailed-design.md)。

JLC Hardware Learning 对话、学习框与飞书原生画板/文档的单向学习笔记同步设计见 [`lark-learning-note-integration.md`](lark-learning-note-integration.md)，本地包和云端绑定契约分别见 [`learning-note-package.schema.json`](../contracts/learning-note-package.schema.json) 与 [`lark-learning-note-binding.schema.json`](../contracts/lark-learning-note-binding.schema.json)。

Contract 示例见 [`LearningQuestion`](../contracts/examples/learning-question.example.json)、[`EvidenceBundle`](../contracts/examples/evidence-bundle.example.json) 和 [`TutorAnswer`](../contracts/examples/tutor-answer.example.json)。

## 使用顺序

1. 查方法签名、参数、返回值、枚举或接口时，以 `pro-api-types` 为准。
2. 查限制、备注、运行环境和版本规则时，阅读官方教程快照或在线文档。
3. 查可运行组合用法时，阅读 `sources/core` 和 `sources/examples` 中的官方仓库。
4. 扩展广场用于发现案例；第三方扩展不能覆盖官方签名或授权写操作。

## 目录

- [`source-policy.md`](source-policy.md)：资料权威等级与使用边界。
- [`tutorial-index.md`](tutorial-index.md)：官方教程及离线快照索引。
- [`example-index.md`](example-index.md)：与融合 Skill 各模块相关的官方示例。
- [`api-index-summary.md`](api-index-summary.md)：API 规模、运行时模块、方法级示例覆盖率和未映射调用。
- [`learning-canvas-architecture.md`](learning-canvas-architecture.md)：JLC Hardware Learning 学习画板、选区提问、官方 EasyEDA 证据适配和导师回答协议。
- [`jlc-hardware-learning-detailed-design.md`](jlc-hardware-learning-detailed-design.md)：学习画板 UI、模块接口、状态机、选区算法、存储、安全、测试和实施里程碑。
- [`lark-learning-note-integration.md`](lark-learning-note-integration.md)：普通对话栏、编号学习框、学习笔记包和飞书原生画板/文档的同步边界。
- `../sources/core/`：SDK、API Skill、文档多语言项目和 Run API Gateway。
- `../sources/examples/`：画板、原理图生成、审查、数据手册和 BOM 示例。
- `../sources/integrations/`：固定提交的第三方 UI 集成；不得作为 EasyEDA API 权威来源。
- `../sources/packages/`：固定版本的 `pro-api-types` 包和声明文件。

## 刷新

在 `materials` 的父目录不变时运行：

```powershell
py materials/scripts/refresh_materials_inventory.py
```

验证 JLC Hardware Learning 固定提交、源码哈希、MCP 握手、工具策略和禁用生图边界：

```powershell
node materials/scripts/validate-jlc-hardware-learning-integration.mjs
```

验证详细设计中的官方 API 映射、只读门禁、Contract、遥测策略和文档链接：

```powershell
node materials/scripts/validate-learning-design.mjs
```

验证 JLC Hardware Learning overlay patches 的哈希、顺序应用、源码语法、工具名、许可证入口和生成内容禁用边界：

```powershell
```

重建机器 API 清单和方法级示例索引：

```powershell
cd materials/scripts/api-indexer
npm test
```

刷新只更新清单和哈希，不自动拉取 Git 更新，也不自动升级本机 Skill。更新源代码快照前应先审查上游差异，再明确决定新的固定提交。
