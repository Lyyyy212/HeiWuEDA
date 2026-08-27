# ZhiYuanEDA

[![CI](https://github.com/Lyyyy212/ZhiYuanEDA/actions/workflows/ci.yml/badge.svg)](https://github.com/Lyyyy212/ZhiYuanEDA/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js 18+](https://img.shields.io/badge/Node.js-18%2B-339933?logo=nodedotjs&logoColor=white)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange.svg)](LICENSE)

> 面向嘉立创EDA专业版的受控硬件设计工作台：连接官方 EasyEDA API，组织硬件生命周期，并把每次操作沉淀为可复核证据。

`ZhiYuanEDA` 由个人开发者 **Lyyyy** 独立开发。项目使用官方 EasyEDA API，
但不是嘉立创EDA官方产品，也不代表嘉立创或 EasyEDA 的认可与背书。

本仓库是面向 GitHub 的公开源码版本，不包含本地工程、现场证据、备份、账号信息、
访问凭据或 EasyEDA 项目数据。原创部分依据
[PolyForm Noncommercial 1.0.0](LICENSE) 提供，**禁止商业使用，也不提供商业授权**。

## 它解决什么问题

直接调用 EDA API 很容易把“读到了数据”“切换了页面”“导出成功”和“设计可以投产”混为一谈。
ZhiYuanEDA 在官方 Bridge 与上层工作流之间增加身份绑定、能力白名单、证据封存和写入授权：

| 能力 | ZhiYuanEDA 的处理方式 |
| --- | --- |
| API 调用 | 只允许锁定清单中的官方 `eda.*` 方法，不向业务模块开放任意 JavaScript |
| 页面切换 | 按工程、文档和页面 UUID 精确导航；不保存设计；遍历结束恢复原页面 |
| 原理图审查 | 快照、DRC、BOM、网表、PDF、EPRO 分开执行并交叉核对 |
| PCB 检查 | 设计报告、固定源码版本的 18 项 DFM、制造 SVG、GenCAD 与装配 BOM |
| BOM 回填 | 只允许四个采购字段，并要求独立授权、验收报告和写后回读 |
| 证据留存 | 为请求、响应、目标窗口、Bridge 身份和产物记录 SHA-256 |
| 硬件学习 | 本地画板、结构化问答和 MCP 集成，与 EDA 持久写入隔离 |

## 架构

```mermaid
flowchart LR
    U[用户 / AI Agent] --> L[硬件生命周期]
    U --> C[硬件学习画板]
    C --> L
    L --> G[Guarded Gateway]
    G --> B[官方 EasyEDA Bridge]
    B --> E[嘉立创EDA专业版]
    G --> A[本地证据与归档]
    L --> A
```

- [`packages/easyeda-gateway/`](packages/easyeda-gateway/)：受控的 EasyEDA Bridge/API 适配层。
- [`skills/easyeda-hardware-lifecycle/`](skills/easyeda-hardware-lifecycle/)：从概念到 BOM 回填的五阶段硬件工作流。
- [`integrations/jlc-hardware-learning-plugin/`](integrations/jlc-hardware-learning-plugin/)：本地硬件学习画板和 MCP 集成。
- [`materials/`](materials/)：API 清单、契约、来源锁及固定版本的上游参考源码。

## 当前能力

| 分类 | 已实现能力 | 状态与边界 |
| --- | --- | --- |
| 连接与身份 | 自动发现 `49620-49629`、Bridge 握手、窗口与工程/文档身份核对 | 可用；只连接 `localhost` / `127.0.0.1` |
| 页面导航 | 列出原理图页、精确切页、逐页遍历、列出/激活板级文档 | 可用；临时 UI 状态，不保存设计 |
| 原理图读取 | 元件、引脚、网络、连接拓扑、分组 BOM | 可用；网表失败时明确降级 |
| 正式证据 | whole-schematic PNG/PDF、BOM CSV、JLCEDA 网表、EPRO、严格 DRC | 按能力矩阵受控放行 |
| PCB 分析 | 设计统计、网络长度、DRC 规则组摘要 | 只读 |
| PCB 制造数据 | 18 项 DFM、分层制造 SVG、GenCAD 1.4 | 可用；检查通过不等于投产批准 |
| BOM 工具 | CSV/TSV/TXT/JSON 差异、自包含 `assembly-lite.v1` HTML BOM | 可用；HTML BOM 不是完整几何复刻 |
| 器件建议 | 官方器件库搜索和 100/85/60 评分 dry-run | 只给建议，不绑定、不改字段、不保存 |
| EPRO 图像 | 从 EPRO 生成审查图片 | `DISABLED_BY_POLICY`；EPRO 仅用于归档 |

完整命令和每项限制见
[`packages/easyeda-gateway/README.md`](packages/easyeda-gateway/README.md)。

## 环境要求

- Python 3.11+
- Node.js 18+（仅硬件学习插件、构建与完整质量检查需要）
- 嘉立创EDA专业版
- 官方 [Run API Gateway](https://jlc-ext.com/item/oshwhub/run-api-gateway) 扩展
- 启动本地 Bridge 时，需要官方 `easyeda-api` Skill 的 Node.js 依赖

## 快速开始

### 1. 克隆并安装 Gateway

仓库包含固定 commit 的上游 Git submodule，请递归克隆：

```bash
git clone --recursive https://github.com/Lyyyy212/ZhiYuanEDA.git
cd ZhiYuanEDA
python -m pip install ./packages/easyeda-gateway
python -m easyeda_gateway --version
```

如果已经普通克隆：

```bash
git submodule update --init --recursive
```

### 2. 连接嘉立创EDA

在嘉立创EDA专业版中安装并启用官方 Run API Gateway，允许外部交互，然后执行：

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py start-bridge
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py discover
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py windows
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py export-capabilities
```

`discover` 会验证服务标识为 `easyeda-bridge`。`windows` 用于取得后续命令必须绑定的
工程 UUID、当前文档 UUID 和窗口信息。

### 3. 列出并切换原理图页面

先保留 `windows` 返回的当前工程和当前原理图页 UUID：

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-pages --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --evidence-dir evidence/page-navigation

python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-page-activate --page-uuid <target-page-uuid> --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --evidence-dir evidence/page-navigation
```

需要逐页采集时，使用会在结束后恢复原页面的遍历命令：

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-page-traverse --project-uuid <project-uuid> --document-uuid <origin-page-uuid> --evidence-dir evidence/page-navigation
```

页面激活不会调用保存。单独使用 `schematic-page-activate` 后，如需返回原页，应把当前目标页
作为 `--document-uuid` 身份守卫，再把原页传给 `--page-uuid`；不要把当前 UI 页面当成持久工程状态。

### 4. 生成审查证据

原理图证据包会串行执行 PDF、BOM、网表、EPRO 和 DRC，并在本地做一致性检查：

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py schematic-evidence-bundle --project-uuid <project-uuid> --document-uuid <schematic-uuid> --evidence-dir evidence/schematic
```

常用 PCB 只读检查与导出：

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-report --project-uuid <project-uuid> --document-uuid <pcb-uuid>

python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-dfm-report --material FR4 --thickness-mm 1.6 --project-uuid <project-uuid> --document-uuid <pcb-uuid>

python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-manufacturing-svg-export --project-uuid <project-uuid> --document-uuid <pcb-uuid>

python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py pcb-gencad-export --project-uuid <project-uuid> --document-uuid <pcb-uuid>

python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py ibom-export --project-uuid <project-uuid> --document-uuid <pcb-uuid>
```

每次 Bridge 请求只执行一个官方调用。若 HTTP 超时，网关不会自动重试，因为 EDA 内部操作
可能仍在继续；请先核对当前页面、导出目录和熔断器状态。

## 硬件生命周期

工作流包含五个显式阶段：

```text
concept -> module_design -> schematic_review -> bom_selection -> bom_writeback
```

初始化一个独立工程：

```bash
python skills/easyeda-hardware-lifecycle/scripts/workbench.py init --project <project-directory> --name demo
python skills/easyeda-hardware-lifecycle/scripts/workbench.py scaffold --project <project-directory> --stage concept
python skills/easyeda-hardware-lifecycle/scripts/workbench.py status --project <project-directory>
```

阶段推进依赖可核验产物，而不是只修改一个状态值。BOM 持久回填是单独的受控步骤，当前只允许：

- `Manufacturer`
- `Manufacturer Part`
- `Supplier`
- `Supplier Part`

## 硬件学习插件

学习插件提供本地画板、结构化提问、批注与证据引用，并通过 MCP 与工作台交互。
它不会因为画板操作而自动保存 EasyEDA 设计。

```bash
cd integrations/jlc-hardware-learning-plugin
npm ci
npm run quality
npm run dev
```

插件说明见
[`integrations/jlc-hardware-learning-plugin/README.md`](integrations/jlc-hardware-learning-plugin/README.md)。

## 官方扩展能力移植

以下能力基于固定 commit 的官方 EasyEDA 扩展源码进行受控适配，而不是直接执行未经约束的上游 UI：

| 上游扩展 | 本地能力 |
| --- | --- |
| `eext-netlist-explorer` | 原理图网表与拓扑分析 |
| `eext-export-design-report` | PCB 设计报告 |
| `eext-bom-compare` | BOM 规范化与逐位号差异 |
| `eext-interactive-html-bom` | 轻量交互装配 BOM |
| `eext-jlc-order-dfm-checker` | 固定 18 项 PCB DFM |
| `eext-export-pcb-to-svg` | 分层制造 SVG |
| `eext-export-gencad` | GenCAD 1.4 |
| `eext-ai-device-standardization` | 器件匹配 dry-run |
| `easyeda-api-skill` | 本地 Bridge 与服务握手 |

每个仓库的锁定 commit、参考文件、许可证和移植边界见
[`MIGRATION_SOURCES.md`](packages/easyeda-gateway/MIGRATION_SOURCES.md)、
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 和
[`materials/manifests/sources.lock.json`](materials/manifests/sources.lock.json)。

## 目录结构

```text
ZhiYuanEDA/
├─ packages/easyeda-gateway/             # Python Gateway 与测试
├─ skills/easyeda-hardware-lifecycle/    # 五阶段工作流与 CLI
├─ integrations/jlc-hardware-learning-plugin/ # 学习画板与 MCP
├─ materials/manifests/                  # API 清单、来源锁、契约索引
├─ materials/sources/                    # 固定版本的上游子模块与 API 类型
├─ examples/api-plans/                   # 只读计划示例
└─ scripts/release/                      # GitHub 发布检查
```

## 安全边界

- 默认只读；所有操作都应绑定明确的工程和文档 UUID。
- 页面切换是 `EPHEMERAL_NAVIGATION`，不保存、不关闭页面，也不修改文档内容。
- 普通业务模块不能提交任意 JavaScript，只能调用清单中的官方方法或固定模板。
- BOM 持久写只允许四个采购字段，且必须具备明确授权、验收报告和写后回读。
- Bridge 超时不自动重试；未知或未完成资格验证的导出组合会在调用前拒绝。
- current-page PNG/PDF/SVG、whole-schematic SVG、BOM XLSX、Protel2 网表和 EPRO2
  当前不在放行矩阵中。
- DRC 零错误、DFM 通过、导出成功和证据一致都不等于可制造性或量产批准。

发现安全问题时请遵循 [`SECURITY.md`](SECURITY.md)，不要在公开 Issue 中上传真实工程、
UUID、BOM、网表、截图、Bridge 日志、凭据或本地绝对路径。

## 兼容性标识

公开展示品牌已经更名为 ZhiYuanEDA。以下技术标识继续保留，避免破坏安装脚本、
本地证据和既有学习数据：

- Python 分发包：`easyeda-workbench-gateway`
- Python 模块与 CLI：`easyeda_gateway` / `easyeda-gateway`
- 本地状态目录：`.easyeda-hardware-workbench/`
- Schema 与 API 契约中的既有 `easyeda.*` 标识

## 离线验证

GitHub Actions 会执行 Gateway 单元测试、wheel 许可证检查、生命周期测试、学习契约校验、
插件冷安装探测和 MCP 探测。也可以在本地运行同一组核心检查：

```bash
python -m unittest discover -s packages/easyeda-gateway/tests -t packages/easyeda-gateway -v
cd skills/easyeda-hardware-lifecycle/scripts
python -m unittest discover -s tests -v
cd ../../..
node materials/scripts/validate-learning-design.mjs
node materials/scripts/validate-jlc-hardware-learning-integration.mjs
node materials/scripts/validate-jlc-hardware-learning-plugin.mjs integrations/jlc-hardware-learning-plugin
cd integrations/jlc-hardware-learning-plugin
npm ci
npm run quality
cd ../..
```

构建并核对 Python 发布包：

```bash
python -m pip wheel --no-deps --wheel-dir dist ./packages/easyeda-gateway
python scripts/release/verify_wheel.py dist/easyeda_workbench_gateway-0.8.0-py3-none-any.whl
```

这些测试只证明离线代码、契约和发布包的一致性。真实 EasyEDA 验收必须连接官方 Bridge，
记录操作前后的工程/文档身份，并继续遵守只读和显式授权边界。

## 参与贡献

欢迎提交用于非商业场景的 Issue 和 Pull Request。修改前请阅读
[`CONTRIBUTING.md`](CONTRIBUTING.md)，并确保没有提交真实工程数据、凭据、现场证据或来源不明的第三方代码。

## 许可证

Lyyyy 原创部分采用 [PolyForm Noncommercial 1.0.0](LICENSE)，禁止商业使用。
由于这一限制，本项目属于 **source-available**，而不是 OSI 定义的开源软件。

第三方子模块、运行时和硬件学习组件继续遵循 Apache-2.0、MIT、BSD-3-Clause、tldraw
等各自条款。特别注意：当前 tldraw 许可证不允许在没有相应授权的情况下用于生产环境；
详见 [`LICENSE_SCOPE.md`](LICENSE_SCOPE.md) 和
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 发布状态

- GitHub 源码发布：已就绪，默认分支为 `main`。
- Gateway：`0.8.0`。
- 硬件学习插件：`0.1.3`。
- 嘉立创EDA拓展广场：当前仓库不是可直接安装的 `.eext` 包；上架版本仍需单独制作、签名和真实环境验收。

版本变化见 [`CHANGELOG.md`](CHANGELOG.md)，发布步骤见 [`PUBLISHING.md`](PUBLISHING.md)。
