# 黑五EDA Gateway

这是工作台的底层 EasyEDA API 适配层。它复用官方 `easyeda-api` Bridge Server 与官方 `Run API Gateway` 扩展，不修改上游材料快照，也不向业务模块暴露任意 JavaScript 执行入口。

## 安全边界

- 仅连接 `127.0.0.1` / `localhost`，并验证 `/health` 的 `service === "easyeda-bridge"`。
- 业务调用使用锁定清单中的规范方法 ID，例如 `DMT_Project.getCurrentProjectInfo#1`。
- 安装包内置与工作台同哈希的锁定 API manifest；在工作台外执行时不依赖当前目录，开发态仍优先使用仓库材料。
- 调用参数是 JSON；枚举使用 `{ "$enum": "EPCB_LayerId.TOP" }`，执行器会先核对枚举与成员。
- 大对象查询可以使用调用级 `pick` 白名单，只返回指定的顶层字段，避免把完整工程树输出到终端。
- 每次执行前在同一段 EDA 代码中重读工程、文档和文档类型；身份漂移立即终止。
- 写计划还要绑定本适配器版本与实际启动的官方 Bridge 脚本 SHA-256；缺少可信 `.runtime/easyeda-bridge.json` 时不执行写入。
- `READ`、`EPHEMERAL_WRITE`、`PERSISTENT_WRITE` 分级验证。写入当前只允许原理图页上的 `SCH_PrimitiveComponent.modify` 修改 BOM 四个采购字段；持久写还必须包含一次受控 `SCH_Document.save`，并提供独立授权与验收报告。
- 原理图图页导航使用独立的 `EPHEMERAL_NAVIGATION` 固定适配器：只允许在当前工程、当前原理图内按 UUID 列出/激活/遍历图页，不保存、不关闭图页、不修改文档；遍历会恢复原页，超时不重试。
- 每次执行生成 `request.json`、`result.json` 和 `envelope.json`，记录清单身份、Bridge 身份、目标窗口和 SHA-256。
- `schematic-snapshot`、`pcb-report` 与 `ibom-export` 只能选择内置固定模板，不能接受任意 JavaScript；读取前后会再次核对工程、文档和文档类型。
- 所有导出先经过能力矩阵和共享的单飞熔断器：未知、仅文档声明或已知会卡页的组合在 `/execute` 前拒绝；一次 Bridge 请求只执行一个官方调用，超时不重试并保持熔断器 `OPEN`。
- `schematic-export` 是独立的固定兼容适配器：普通计划仍拒绝 deprecated 方法，只有该适配器能用官方旧导出方法生成不覆盖的本地证据文件。当前仅放行 whole-schematic PNG/PDF，所有 current-page 视觉导出均因已知卡页风险被阻断。多图页的官方 PNG 可能返回一个仅含 PNG 的 ZIP；适配器会按官方条目顺序安全校验并暴露页清单，不会将该容器误当成坏 PNG，也不会借用 EPRO 渲染。`schematic-native-pdf-render` 可把已经封存的官方 PDF 在本地渲染为最长边默认 6144 px 的逐页 PNG；它不连接 Bridge，也不重复官方导出。

## 已移植能力

- 官方 Netlist Explorer：原理图网表、引脚网络表、连接拓扑、连接器对照和分组 BOM。官方 Beta 网表导出失败时降级为元件/引脚快照，并明确标记连接关系不可用。
- 官方 Export Design Report：PCB 元件/焊盘/过孔/走线统计、网络长度和 DRC 规则组摘要。
- 官方 BOM Compare：CSV、TSV/TXT、JSON 的中英文字段映射、重复列提示和逐位号差异。
- 官方 Interactive HTML BOM：自包含、可搜索、可按正反面筛选的 `assembly-lite.v1` HTML。当前为轻量装配视图，不等同于官方插件的完整几何渲染。
- 官方 JLC PCB DFM：固定调用源码锁定的 18 项检查，拦截插件日志、面板、IFrame 和扩展配置写入，只保存不可覆盖的本地 JSON；结果区分 `PASS`、`REVIEW_REQUIRED`、`BLOCKED_BY_DFM`，零错误仍不等同于可投产。
- 官方制造 SVG：固定调用 `getGerberFile → Gerber 解析 → 分层 SVG ZIP`，把插件下载重定向到证据目录；本地拒绝路径穿越、无 SVG、无效 XML 与超大解压内容。
- 官方 GenCAD：固定导出 GenCAD 1.4，检查 HEADER、BOARD、COMPONENTS、SIGNALS 和终止段，并记录器件/网络数量。
- 官方器件标准化 dry-run：读取当前原理图元件并使用 `LIB_Device.search#1` 查找候选，复用官方 100/85/60 默认评分；只生成本地建议报告，不绑定器件、不修改字段、不保存原理图。
- 官方原理图视觉导出：已验证的 whole-schematic PNG/PDF、前后页身份校验、文件签名/尺寸/SHA-256 校验和不可覆盖证据目录。单图页返回直接 PNG；多图页可返回官方 ZIP-of-PNG，网关会限制条目类型、数量、路径、压缩方式与大小，并为每一页记录原始条目名、尺寸和 SHA-256。官方 PDF 可在导出身份再次确认后由 Poppler 本地渲染为有尺寸上限的高清 PNG，证据同时保存源 PDF、渲染器和每页摘要。由于官方方法自 EDA v4.1 起标记废弃，该能力被隔离在兼容适配器中，不进入普通 typed plan。
- 旧 `$jlc` 正式证据导出：BOM CSV、JLCEDA Pro 网表、EPRO 源文件、严格 DRC JSON；每项为独立 Bridge 请求，并有格式与身份验证。
- 完整原理图证据包：PDF、BOM、网表、EPRO、DRC 串行隔离执行，再在本地核对位号集合、数量、重复项、PDF 可见位号和 DRC 状态。
- EPRO 源码归档：文档/工程 EPRO 仍可由正式导出适配器保存给审计或归档消费者，但不再作为图像来源。
- EPRO 图像策略：旧单页和全工程 EPRO 渲染器仅保留为解析器维护代码；两个 CLI 图像入口均前置返回 `DISABLED_BY_POLICY`。画板接收官方 `Current Schematic` PNG，或从摘要封存的官方 `Current Schematic` PDF 本地派生的受限高清 PNG；审查/归档仍可直接使用官方 PNG 或 PDF。
- 审计与归档：PDF 文本层缺位作为复核项而非“视觉对象缺失”证据；`evidence-archive` 生成不覆盖 ZIP，并在包内记录每个证据文件的大小和 SHA-256。
- Bridge 重启后可显式使用 `--allow-window-rebind`；它要求同时提供精确 project/document UUID 且当前只有一个连接窗口，任何歧义都阻断。

完整上游仓库、commit 与复用边界见 [MIGRATION_SOURCES.md](MIGRATION_SOURCES.md)。

## 命令

从工作台根目录执行：

```powershell
py -m easyeda_gateway --version
py skills/easyeda-hardware-lifecycle/scripts/api_contract.py identity --manifest materials/manifests/api-manifest.json
py skills/easyeda-hardware-lifecycle/scripts/api_contract.py validate-plan --manifest materials/manifests/api-manifest.json --plan examples/api-plans/read-current-context.json
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py discover
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py windows
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py probe --evidence-dir evidence/gateway
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-pages --evidence-dir evidence/gateway
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-page-activate --page-uuid <target-page-uuid> --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --evidence-dir evidence/gateway
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-page-traverse --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --evidence-dir evidence/gateway
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py board-documents --project-uuid <project-uuid> --document-uuid <origin-document-uuid> --evidence-dir evidence/gateway
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py board-document-activate --target-uuid <target-uuid> --target-document-type 3 --project-uuid <project-uuid> --document-uuid <origin-document-uuid> --evidence-dir evidence/gateway
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py export-capabilities
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py export-safety-status
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-snapshot --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-export --format PNG --scope current-schematic --project-uuid <project-uuid> --document-uuid <schematic-uuid> --evidence-dir .easyeda-hardware-workbench/evidence/schematic-exports
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-native-png-normalize --source <official-png-or-zip> --source-envelope <failed-export-envelope.json> --identity-before <before.json> --identity-after <after.json> --evidence-dir <derived-evidence-dir> --output <normalization-execution.json>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-native-pdf-render --source-execution <official-pdf-execution.json> --identity-before <before.json> --identity-after <after.json> --evidence-dir <derived-evidence-dir> --output <pdf-render-execution.json> --max-long-edge 6144
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-bom-export --format csv --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-netlist-export --format jlceda --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-source-export --format epro --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-project-source-export --format epro --project-uuid <project-uuid> --document-uuid <active-page-uuid> --output project.epro
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-drc --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-evidence-bundle --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py evidence-archive --source-dir evidence/gateway --output evidence-gateway.zip
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-report --project-uuid <project-uuid> --document-uuid <pcb-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-dfm-report --material FR4 --thickness-mm 1.6 --project-uuid <project-uuid> --document-uuid <pcb-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-manufacturing-svg-export --project-uuid <project-uuid> --document-uuid <pcb-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-gencad-export --project-uuid <project-uuid> --document-uuid <pcb-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py device-match-dry-run --designator U1 --max-components 25 --max-candidates 5 --project-uuid <project-uuid> --document-uuid <schematic-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py ibom-export --project-uuid <project-uuid> --document-uuid <pcb-uuid>
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py bom-diff --old old.csv --new new.csv
```

若 Bridge 尚未运行：

```powershell
py skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py start-bridge
```

这只启动固定的官方 Bridge 脚本；不会自动安装依赖或替换 EasyEDA 扩展。EasyEDA 专业版仍需安装参考页中的 `Run API Gateway`，并在扩展管理器开启“允许外部交互”。PDF 校验使用 Python `pypdf`（包依赖已声明），高清逐页渲染使用 Poppler `pdftoppm`，可通过 `--pdftoppm` 指定。旧 EPRO 渲染依赖仍保留给维护测试，但产品命令不会执行该渲染。

`current-page` PNG/PDF/SVG、whole-schematic SVG、BOM XLSX、Protel2 网表和 EPRO2 当前都会在 Bridge 调用前拒绝；DFM、制造 SVG 和 GenCAD 已完成本机真实 PCB 串行资格测试。两个 EPRO 图像渲染命令仍按产品策略拒绝。不要为了“试一下”绕过矩阵；HTTP 超时不能取消 EasyEDA 内部仍在运行的导出。

`schematic-native-png-normalize` 只处理已经落盘且具有封存失败 envelope、导出前后精确身份记录的官方 PNG 产物。它不连接 Bridge，`easyedaApiCallCount` 固定为 `0`，用于把旧版误判为签名错误的官方 ZIP-of-PNG 安全转成逐页原生 PNG 证据；它不是失败导出的自动重试入口。

`schematic-native-pdf-render` 只接受 `PASS` 的官方 whole-schematic PDF execution 及其封存 envelope，并要求渲染前后的工程/文档身份完全一致。它拒绝加密、过大、页数超限或摘要不匹配的 PDF；默认最长边 6144 px、硬上限 8192 px，同时限制单页和总 PNG 字节数。输出记录 `easyedaApiCallCount=0`、Poppler 路径/版本/SHA-256、源 PDF SHA-256 和每一页 PNG SHA-256。

## Python API

```python
from easyeda_gateway import ApiRegistry, BridgeExecutor, EasyedaExportAdapter, EasyedaPageNavigator, SchematicExportSpec, SchematicPageNavigationSpec, discover_bridge, load_json

registry = ApiRegistry.from_file("materials/manifests/api-manifest.json")
executor = BridgeExecutor(registry, discover_bridge())
result = executor.execute(load_json("plan.json"), "evidence/gateway")

exporter = EasyedaExportAdapter(registry, discover_bridge())
page = exporter.execute(SchematicExportSpec(), "evidence/schematic-exports")

navigator = EasyedaPageNavigator(registry, discover_bridge())
pages = navigator.execute(SchematicPageNavigationSpec("list"), "evidence/page-navigation")
```

原始 `/execute` 只存在于本包的 `BridgeClient` 内部；生命周期兼容入口也复用该传输。普通计划应通过 `BridgeExecutor`，跨多个读取 API 的迁移能力应通过 `CompositeReadExecutor` 的命名模板执行。
