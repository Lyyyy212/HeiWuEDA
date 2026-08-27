# EasyEDA 官方 API 机器索引摘要

本页由 `materials/scripts/api-indexer/build-api-indexes.mjs` 从固定官方快照生成。它不连接 EasyEDA，不执行任何工程读写。

## 固定输入

- API 签名：`@jlceda/pro-api-types` 0.4.15，声明 SHA-256 `088146a3e913a7e08c164a4c7c60aae41c0cfecafe18697c68d6aa470ffa4254`。
- 官方参考：`easyeda-api-skill` 1.1.22，固定提交 `213856a67d0237d7d06c4a5f44c4310ff633e78d`。
- 官方仓库：14 个固定 Git 快照。
- 机器输出：[`api-manifest.json`](../manifests/api-manifest.json) 与 [`api-example-index.json`](../manifests/api-example-index.json)。

## API 规模

- 127 个类、73 个枚举、122 个接口、24 个类型别名。
- 1559 个类方法，其中 746 个直接返回 `Promise`。
- `eda` 暴露 95 个运行时模块。
- 346 个声明能链接到同一固定版本的官方参考 Markdown。

| 域 | 类 | 方法 | 运行时模块 |
| --- | --- | --- | --- |
| DMT | 11 | 87 | 11 |
| EDA | 1 | 0 | 0 |
| IPCB | 18 | 452 | 0 |
| ISCH | 13 | 322 | 0 |
| LIB | 10 | 71 | 10 |
| PCB | 25 | 291 | 25 |
| PNL | 1 | 1 | 1 |
| SCH | 21 | 147 | 21 |
| SYS | 27 | 188 | 27 |

## 官方调用样本

- 不同直接调用：630。
- 总命中：4694（代码 546，文档 4148）。
- 已映射调用：629；未映射调用：1。
- 覆盖运行时类方法：629/785（80.13%）。

### 仓库覆盖

| 仓库 | 分组 | 不同调用 | 代码命中 | 文档命中 |
| --- | --- | --- | --- | --- |
| easyeda-api-skill | core | 626 | 1 | 4113 |
| eext-generate-schematic-from-netlist | examples | 12 | 110 | 3 |
| eext-ai-device-standardization | examples | 40 | 89 | 0 |
| eext-extension-demo | examples | 33 | 76 | 0 |
| eext-interactive-html-bom | examples | 25 | 36 | 31 |
| eext-netlist-explorer | examples | 15 | 54 | 0 |
| eext-export-design-report | examples | 23 | 50 | 0 |
| eext-excalidraw | examples | 10 | 49 | 0 |
| eext-datasheet-helper | examples | 8 | 32 | 0 |
| eext-run-api-gateway | core | 10 | 30 | 1 |
| eext-api-test-tool | examples | 4 | 8 | 0 |
| eext-bom-compare | examples | 5 | 8 | 0 |
| pro-api-sdk | core | 2 | 3 | 0 |
| easyeda-api-i18n | core | 0 | 0 | 0 |

### 高频调用

| 调用 | 类方法 | 命中 | 仓库数 |
| --- | --- | --- | --- |
| `eda.lib_Device.search()` | `LIB_Device.search` | 186 | 3 |
| `eda.pcb_MathPolygon.createPolygon()` | `PCB_MathPolygon.createPolygon` | 136 | 1 |
| `eda.sys_I18n.text()` | `SYS_I18n.text` | 131 | 12 |
| `eda.sch_PrimitiveComponent.create()` | `SCH_PrimitiveComponent.create` | 106 | 3 |
| `eda.pcb_PrimitiveComponent.create()` | `PCB_PrimitiveComponent.create` | 98 | 1 |
| `eda.pcb_PrimitivePad.create()` | `PCB_PrimitivePad.create` | 98 | 1 |
| `eda.lib_LibrariesList.getPersonalLibraryUuid()` | `LIB_LibrariesList.getPersonalLibraryUuid` | 80 | 2 |
| `eda.pcb_PrimitiveAttribute.get()` | `PCB_PrimitiveAttribute.get` | 66 | 1 |
| `eda.sch_PrimitiveComponent.delete()` | `SCH_PrimitiveComponent.delete` | 64 | 3 |
| `eda.dmt_EditorControl.openDocument()` | `DMT_EditorControl.openDocument` | 62 | 2 |
| `eda.sch_PrimitiveAttribute.get()` | `SCH_PrimitiveAttribute.get` | 61 | 1 |
| `eda.sys_Message.showToastMessage()` | `SYS_Message.showToastMessage` | 59 | 7 |
| `eda.pcb_PrimitiveComponent.delete()` | `PCB_PrimitiveComponent.delete` | 54 | 2 |
| `eda.pcb_PrimitiveVia.create()` | `PCB_PrimitiveVia.create` | 50 | 1 |
| `eda.pcb_PrimitiveAttribute.getAllPrimitiveId()` | `PCB_PrimitiveAttribute.getAllPrimitiveId` | 47 | 1 |
| `eda.pcb_PrimitiveLine.create()` | `PCB_PrimitiveLine.create` | 45 | 1 |
| `eda.sch_PrimitiveRectangle.create()` | `SCH_PrimitiveRectangle.create` | 45 | 1 |
| `eda.lib_Symbol.search()` | `LIB_Symbol.search` | 44 | 2 |
| `eda.pcb_PrimitiveString.create()` | `PCB_PrimitiveString.create` | 42 | 2 |
| `eda.sch_PrimitiveAttribute.getAllPrimitiveId()` | `SCH_PrimitiveAttribute.getAllPrimitiveId` | 42 | 1 |

### 未映射调用

未映射并不自动等于错误：它可能是固定示例使用了比当前类型包更新、已移除或动态注入的接口。进入融合 Skill 前必须逐项审查，不能猜签名。

| 调用 | 状态 | 命中 | 首个位置 |
| --- | --- | --- | --- |
| `eda.dmt_Schematic.getAllSchematicDocumentsInfo()` | unknown-method | 1 | sources/core/easyeda-api-skill/SKILL.md:450 |

## 消费约定

1. 生成代码前先查 `api-manifest.json` 的确切签名、返回值、枚举和发布标签。
2. 查用法时以 `api-example-index.json` 的固定提交、文件和行号回到官方上下文。
3. `mappingStatus !== "mapped"` 的调用不得自动生成。
4. 示例覆盖率只表示本地官方快照中存在直接调用，不代表 API 可在任意文档状态、权限或版本下执行。
