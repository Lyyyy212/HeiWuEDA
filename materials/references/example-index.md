# 官方示例索引

这些仓库均来自 `github.com/easyeda` 官方组织，并固定到 `sources.lock.json` 记录的提交。示例用于学习调用组合，不替代类型定义和官方方法备注。

| 模块 | 本地仓库 | 主要参考点 |
|---|---|---|
| 底层开发模板 | [`pro-api-sdk`](../sources/core/pro-api-sdk) | 扩展项目结构、构建、菜单和基础调用 |
| AI Bridge | [`easyeda-api-skill`](../sources/core/easyeda-api-skill) | Bridge Server、API 参考、文档格式 |
| EasyEDA 侧 Bridge | [`eext-run-api-gateway`](../sources/core/eext-run-api-gateway) | WebSocket、MessageBus、窗口注册与存储 |
| 基础 API 操作 | [`eext-extension-demo`](../sources/examples/eext-extension-demo) | 原理图/PCB 图元读取、创建、修改、删除 |
| API 测试 | [`eext-api-test-tool`](../sources/examples/eext-api-test-tool) | API 测试界面和 iframe |
| EasyEDA 内嵌画板参考 | [`eext-excalidraw`](../sources/examples/eext-excalidraw) | 官方 iframe 集成模式；不再作为用户学习画板主实现 |
| 原理图生成 | [`eext-generate-schematic-from-netlist`](../sources/examples/eext-generate-schematic-from-netlist) | 器件搜索、放置、引脚和导线创建 |
| 拓扑解析 | [`eext-netlist-explorer`](../sources/examples/eext-netlist-explorer) | 器件、引脚、网表读取和选择定位 |
| 后期审查 | [`eext-export-design-report`](../sources/examples/eext-export-design-report) | PCB 网络、长度、规则组和报告导出 |
| 数据手册学习 | [`eext-datasheet-helper`](../sources/examples/eext-datasheet-helper) | 选中器件、外部请求、数据手册与问答 UI |
| 器件标准化 | [`eext-ai-device-standardization`](../sources/examples/eext-ai-device-standardization) | 库搜索、器件标准化、跨页和 DRC；写逻辑只作研究 |
| BOM 对比 | [`eext-bom-compare`](../sources/examples/eext-bom-compare) | BOM 比较与结果展示 |
| BOM/PCB 提取 | [`eext-interactive-html-bom`](../sources/examples/eext-interactive-html-bom) | PCB 图元、网络、属性和 BOM 数据提取 |

## 仅登记、暂不下载

- `eext-api-debug-tool`：仓库较大，需要真实调试时再固定提交。
- `eext-simulation-with-ngspice`：适合后续学习仿真模块，当前不进入底层 API 资料包。
- `eext-circuitjs1-simulator`：适合交互式学习仿真，后续与画板模块一起评估。

完整官方仓库目录见 [`../manifests/official-repository-catalog.json`](../manifests/official-repository-catalog.json)。

## 第三方学习画板

用户侧学习画板采用独立维护的 [`JLC Hardware Learning`](../../integrations/jlc-hardware-learning-plugin)，仅提供画布、选区、标注、本地持久化与本地导出，不包含生图、改图、AI HTML、Slides 或遥测功能。它是 I1 级 UI 集成，不属于 EasyEDA 官方 API 证据。架构见 [`learning-canvas-architecture.md`](learning-canvas-architecture.md)。
