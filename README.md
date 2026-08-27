# ZhiYuanEDA

[![CI](https://github.com/Lyyyy212/ZhiYuanEDA/actions/workflows/ci.yml/badge.svg)](https://github.com/Lyyyy212/ZhiYuanEDA/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js 18+](https://img.shields.io/badge/Node.js-18%2B-339933?logo=nodedotjs&logoColor=white)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange.svg)](LICENSE)

<p align="center">
  <img src="docs/assets/zhiyuaneda-hero.png" alt="ZhiYuanEDA 连接硬件设计、受控 API 网关与学习画板" width="100%">
</p>

> 面向嘉立创EDA专业版的模块化硬件工作台，围绕“硬件设计全生命周期”和“硬件学习与知识沉淀”两条核心链路组织功能。

`ZhiYuanEDA` 由个人开发者 **Lyyyy** 独立开发。项目连接官方 EasyEDA API，
但不是嘉立创EDA官方产品，也不代表嘉立创或 EasyEDA 的认可与背书。

本仓库是面向 GitHub 的公开源码版本，不包含真实工程、现场证据、账号信息、访问凭据或
EasyEDA 项目数据。原创部分依据 [PolyForm Noncommercial 1.0.0](LICENSE) 提供，
**禁止商业使用，也不提供商业授权**。

## 第一次来？先看这里

可以把嘉立创EDA理解成真正绘制和保存电路的“设计桌”，把 ZhiYuanEDA 理解成桌旁的
“硬件协作助手”：它先确认你正在操作哪个工程、哪一张图，再帮助检查设计、整理证据、
选择器件，或者把电路放到学习画板上讲明白。

它主要解决三件事：

| 你遇到的问题 | ZhiYuanEDA 怎么帮你 |
| --- | --- |
| **设计过程容易乱** | 把需求、模块设计、原理图审查、BOM 选型和回填拆成有产物、有门禁的步骤 |
| **API 操作怕跑错工程** | 每次连接都核对窗口、工程和文档 UUID，只允许清单中的官方方法，并保留执行证据 |
| **原理图看不懂、知识难沉淀** | 把官方证据导入学习画板，框选某段电路提问，得到带证据的讲解、标注和学习笔记 |

### 30 秒导览

1. **连接设计**：打开嘉立创EDA工程，通过官方 Bridge 接入当前窗口。
2. **确认对象**：ZhiYuanEDA 核对工程、图页和文档类型，防止对错页面操作。
3. **选择链路**：要推进项目就进入“硬件设计链”；要理解电路就进入“硬件学习链”。
4. **留下证据**：读取、审查、导出和受控写回都会生成可核对记录，而不是只返回一句结论。

| 如果你现在想…… | 从这里开始 |
| --- | --- |
| 从需求开始做一个硬件项目 | `concept`，进入硬件设计链 |
| 审查已有原理图或 PCB | `schematic_review`，采集正式证据 |
| 确定器件和采购信息 | `bom_selection`，形成有依据的最终 BOM |
| 看懂某一段原理图 | 学习画板框选后使用 `explain-selection` |
| 追踪信号、电源或比较方案 | 使用 `trace-signal`、`power-path` 或 `compare-options` |

> 关键原则：学习链只负责“看懂、解释和记录”，不会直接修改 EasyEDA；需要修改设计时，
> 结论必须重新进入设计链并通过相应门禁。

## 核心重点：学习画板与学习笔记

这不是给原理图加一张普通截图，也不是让 AI 对着图片自由发挥。ZhiYuanEDA 把
**官方原理图证据、明确的学习范围、对话问题、证据化回答和长期笔记**连接在一起，
让“这块电路为什么这样设计”能够被准确提问、持续追问，并在下次打开项目时继续学习。

### 学习画板能做什么

学习画板是原理图旁边的一张持久化教学白板：原理图作为受保护底图，用户在上面划分模块、
圈出问题、添加说明，但画板操作不会改动 EasyEDA 工程。

| 功能 | 通俗解释 |
| --- | --- |
| 官方证据导入 | 把经过身份和摘要校验的 EasyEDA 原理图视觉材料放进画板，不用来历不明的截图代替 |
| 多图页画布 | 每张学习页分别保存原理图、视图、选区和标注，不把不同页面的证据混在一起 |
| 编号学习框 | 用“学习框 1、2、3……”把电源、运放、接口等区域划成稳定模块；编号保存后不会因重启改变 |
| 选区与提问 | 可以框选一个或多个模块，在正常对话中问“模块 1 为什么这样接”或“比较 1 和 2” |
| 教学标注 | 回答可以落成文字、便签、高亮、矩形和箭头，直接指向对应电路位置 |
| 画板编辑 | 支持选择、平移、画笔、橡皮擦、多选、复制、撤销/重做、缩放、小地图和样式调整 |
| 证据保护 | 导入的原理图默认锁定；普通删除键只删除标注，删除底图必须经过明确确认 |
| 本地导出 | 可导出当前页 PNG/SVG、选区 PNG 和完整 JSON 备份，方便分享或恢复 |

学习框不是普通矩形。它带有页面内唯一且持续递增的编号：删除后不复用，复制时分配新编号，
旧画板迁移时也会确定性补号。因此“模块 3”始终指向同一页上的同一个学习范围，
不会因为鼠标刚好点中了别处而改变含义。

### 一次完整学习怎样发生

1. **导入原理图**：用户选择默认配色或黑白配色。默认路线从官方 whole-schematic PDF
   本地渲染最长边 6144 px 的逐页 PNG；明确要求更小或更快时才使用原生 PNG 路线。
2. **划分模块**：在原理图上创建编号学习框，例如把输入保护框成“模块 1”，把运放级框成“模块 2”。
3. **在对话中提问**：直接问“模块 2 的两个电阻为什么这样取值？”；画板本身不再放置另一个聊天面板。
4. **固定问题上下文**：系统记录当前画板页、学习框编号、shape ID、选区范围、图片摘要和 EasyEDA 文档身份。
5. **补充硬件证据**：按需读取器件属性、引脚、网络、BOM 或数据手册；证据不足时标记未知，而不是猜测。
6. **回答并标注**：回答明确区分证据、推断、未知项和安全提示；经允许后把简短结论标回画板。
7. **保存学习历史**：问题、证据、导师基线、实际展示的回答和会话顺序分别保存，重启后可以继续追问。

例如，用户框住一个 LDO 电源模块并问“输入输出电容为什么不同”。学习记录不只保存一句回答，
还会保存它对应哪个图页、哪个学习框、覆盖了哪张原理图、使用了哪些器件/网络证据、
有哪些额定值尚未确认，以及回答中建议下一步查哪一项数据手册参数。

### 画板便签和学习笔记有什么区别

| 类型 | 作用 | 保存内容 |
| --- | --- | --- |
| **画板文字/便签** | 在电路旁留下短说明，适合快速标出“反馈电阻”“注意极性”等信息 | 文字、位置、大小、颜色、样式和所属画板页 |
| **结构化学习笔记** | 把一次或多次学习过程整理成可以检索、恢复和迁移的完整记录 | 原理图证据、编号学习框、问题、回答、证据状态、未知项、对话顺序和内容摘要 |

结构化笔记按学习框组织，而不是按聊天时间简单堆叠。一个笔记包包含：

- 工程和画板图页信息。
- 原理图学习画板快照与 SHA-256。
- “模块 1、模块 2……”的编号索引、范围和关联原理图。
- 每个模块下面按顺序排列的问题与实际回答。
- 回答使用的证据状态、仍未确认的事项和后续检查建议。
- 普通教学标注以及学习框与对话之间的稳定关联。
- 用于判断内容是否变化的 `contentSha256` 和同步记录。

本地数据按用途分开保存：

```text
<project>/.easyeda-hardware-workbench/learning/
├─ questions/   # 不可变的问题记录
├─ evidence/    # 证据包
├─ answers/     # 可复现的导师回答基线
├─ responses/   # 实际展示给用户的完整回答
├─ sessions/    # 同一画板页上的有序会话
├─ notes/       # 学习笔记包与 Markdown 预览
└─ lark/        # 后续云端绑定与验证记录
```

生成本地 JSON 笔记包和 Markdown 预览：

```bash
python skills/easyeda-hardware-lifecycle/scripts/workbench.py learning-note-package --project <project-directory> --canvas <hardware-learning-canvas.json> --page-id <page-id> --output <learning-note.json> --markdown-output <learning-note.md>
```

### 笔记如何延续和迁移

- `learning-resume` 可以在 Widget 或 Codex 重启后恢复同一画板页上的有序问答历史。
- 对旧回答的修正会保存成新的对话回合，不会偷偷重写不可变的历史记录。
- 学习笔记包会验证学习框是否仍然存在；编号缺失、重复或跨页引用会直接阻止打包。
- 本地包可以生成面向飞书文档和原生画板的结构化计划，目录包括工程信息、原理图画板、
  模块索引、提问与解答、模块关系、待验证项和同步记录。
- 当前输出是 `PLAN_ONLY_NO_CLOUD_WRITE`：生成计划不等于授权写入飞书。首次设计为
  `JLC Hardware Learning -> 飞书` 单向同步，非空同步画板的覆盖仍需明确确认，用户自己的自由笔记不会被覆盖。

因此，学习画板解决“在哪里学、指着哪里问”，学习笔记解决“学过什么、依据是什么、
下次如何接着学”。二者通过稳定的图页 ID、学习框编号、问题 ID 和内容摘要连接起来。

## 项目组成

ZhiYuanEDA 不是一个单独的 API 脚本，而是一组职责隔离、通过明确契约协作的模块：

| 模块 | 位置 | 主要功能 | 服务链路 |
| --- | --- | --- | --- |
| API 契约与注册表 | `easyeda_gateway/contract.py`、`api-manifest.json` | 锁定官方方法 ID、签名、枚举和风险等级；拒绝未知 API | 两条链路共享 |
| Bridge 客户端与窗口守卫 | `client.py`、`window_guard.py`、`executor.py` | 自动发现本地 Bridge、验证 `easyeda-bridge` 握手、绑定窗口/工程/文档身份 | 两条链路共享 |
| 页面与板级文档导航 | `page_navigator.py`、`board_navigator.py` | 列出页面、按 UUID 精确切换、跨页遍历并恢复原页；不保存设计 | 两条链路共享 |
| 原理图读取与证据 | `composite.py`、`exporter.py`、`formal_exporter.py`、`drc.py` | 元件/引脚/网络/拓扑读取，PNG/PDF、BOM、网表、EPRO、DRC 和证据包 | 设计链；为学习链供证 |
| PCB 分析与制造数据 | `official_plugins.py`、`ibom.py` | PCB 设计报告、18 项 DFM、制造 SVG、GenCAD 1.4、交互装配 BOM | 设计链 |
| BOM 与器件工具 | `bom.py`、`device_match.py`、`intelligence.py` | BOM 差异、器件候选评分、连接关系分析；候选结果不自动绑定器件 | 设计链；为学习链供证 |
| 导出安全与证据归档 | `export_safety.py`、`artifact_io.py`、`consistency.py`、`evidence_archive.py` | 能力矩阵、单飞熔断、不可覆盖落盘、跨产物一致性、SHA-256 归档 | 两条链路共享 |
| 生命周期编排器 | `skills/easyeda-hardware-lifecycle/` | 管理阶段、产物、门禁、失效传播和受控推进 | 设计链主控 |
| 学习编排模块 | `hwlifecycle/learning/` | 视觉导入路由、选区问题、证据请求、导师回答、会话恢复和笔记包 | 学习链主控 |
| 硬件学习画板插件 | `integrations/jlc-hardware-learning-plugin/` | 多图页画布、框选、箭头/文字/自由笔、教学标注、本地状态与导出 | 学习链交互层 |
| API 材料与来源锁 | `materials/` | API 类型、JSON Schema、示例索引、固定 commit 的上游源码和许可证 | 两条链路共享 |
| 发布与质量检查 | `.github/workflows/`、`scripts/release/` | 单元测试、契约校验、插件探测、wheel 许可证检查和公开包净化 | 发布链路 |

底层 Python Gateway 的完整类与命令见
[`packages/easyeda-gateway/README.md`](packages/easyeda-gateway/README.md)。

## 两大核心链路

<p align="center">
  <img src="docs/assets/zhiyuaneda-two-core-flows.png" alt="ZhiYuanEDA 两大核心链路：硬件设计链与硬件学习链" width="100%">
</p>

两条链路共享受控 API、身份守卫和证据层：设计链产出的正式证据可以进入学习链；
学习链形成的理解和建议不会反向自动写入设计。

### 链路一：硬件设计全生命周期

这条链路把硬件开发拆成五个可追踪阶段。每一阶段都必须提交结构化产物并通过门禁，
不能仅凭对话中的一句“完成了”直接进入下一阶段。

| 阶段 | 主要功能 | 核心产物与门禁 |
| --- | --- | --- |
| `concept` | 梳理需求、优先级、系统分区、电源域、接口、方案备选和验证策略 | 需求必须可测量、有负责人；架构和验证覆盖完整 |
| `module_design` | 为每个模块定义用途、输入输出、电气约束、接口、计算、实现选项和验证计划 | 模块与接口必须互相引用一致，约束必须显式 |
| `schematic_review` | 绑定当前工程/图页，采集原理图、BOM、网表、PDF/EPRO、DRC，分析连接和风险 | 报告必须绑定当前快照；P0/P1 问题关闭后才能放行 |
| `bom_selection` | 核对 MPN、封装、规格、生命周期、库存、价格和替代料，形成最终 BOM | 不允许歧义/未匹配项；关键器件要有替代料；最终 BOM 固化摘要 |
| `bom_writeback` | 冻结 BOM、生成计划、做可恢复验收、刷新计划、授权保存、写后回读 | 只写四个采购字段；必须验证受保护字段、连接关系和 DRC 未受损 |

设计链的主要能力还包括：

- 原理图页和板级文档按 UUID 导航，跨页采集后恢复原页面。
- 原理图元件、引脚、网络、连接拓扑和分组 BOM 分析。
- whole-schematic PNG/PDF、BOM CSV、JLCEDA 网表、EPRO 与严格 DRC 证据包。
- PCB 元件/焊盘/过孔/走线统计、网络长度和规则组摘要。
- 固定源码版本的 18 项 PCB DFM、分层制造 SVG、GenCAD 1.4 与装配 BOM。
- 器件标准化 dry-run：只输出候选和评分，不绑定、不修改、不保存。
- 上游需求、接口、封装或选型变化时，自动使受影响阶段及下游结论失效。

设计链的数据流：

```text
需求与约束
  -> 系统架构
  -> 模块接口与计算
  -> UUID 绑定的原理图/PCB 证据
  -> 审查结论与整改门禁
  -> 可采购的最终 BOM
  -> 显式授权的四字段回填
  -> 保存后回读与一致性确认
```

### 链路二：硬件学习与知识沉淀

这条链路把 EasyEDA 中的设计转成可框选、可提问、可解释、可恢复的学习材料。
画板负责表达“我在问哪里”，生命周期层负责取得证据和组织回答，两者不会绕过 Gateway。

| 环节 | 主要功能 | 输出 |
| --- | --- | --- |
| 官方证据导入 | 从已封存的官方 PDF 渲染高清逐页 PNG；也支持显式选择原生 PNG 路线 | 带工程/文档身份、主题和 SHA-256 的页面素材 |
| 画板组织 | 多图页管理、底图锁定、框选、多选、缩放、小地图、矩形、箭头、自由笔和文字 | 本地画板状态、选区和视图状态 |
| 选区提问 | 保留画板 shape ID、图片资产、选区范围和 EasyEDA document UUID | `LearningQuestion` / `SelectionEnvelope` |
| 证据补充 | 按问题读取图元、网络、器件属性、BOM 或数据手册证据 | 归一化 `LearningContext` |
| 硬件导师 | 解释电源路径、信号链、器件用途、连接拓扑、BOM 选择和设计风险 | 区分证据、推断、未知项和安全提示的 `TutorAnswer` |
| 教学标注 | 把简短结论写成普通文本、矩形、高亮或箭头 | 幂等画板标注，不修改 EasyEDA |
| 知识沉淀 | 保存问题、回答、会话和画板；导出 PNG/SVG/JSON；生成结构化学习笔记包 | 可恢复会话和可迁移学习笔记 |

学习链当前支持六类问题路由：

- `explain-selection`：框选电路在做什么。
- `trace-signal`：信号从哪里来、到哪里去。
- `explain-component`：芯片、阻容和外围器件为什么这样选择。
- `power-path`：电源如何变换、分配和去耦。
- `review-concept`：当前设计思路可能存在哪些风险。
- `compare-options`：两种器件或电路方案的差异与取舍。

学习链的数据流：

```text
官方 EasyEDA 证据
  -> 本地高清页面素材
  -> 画板选区与自然语言问题
  -> UUID 绑定的补充证据
  -> 硬件导师解释
  -> 文本/矩形/高亮/箭头标注
  -> 会话恢复、PNG/SVG/JSON 和学习笔记包
```

学习模式明确禁用图片生成、按标注改图、遥测、隐式切页、跨页证据混合和 EasyEDA 持久写入。
学习结论如果要变成设计修改，必须重新进入设计链，形成正式产物并通过对应门禁。

## 两条链路如何协同

| 共享能力 | 设计链中的作用 | 学习链中的作用 |
| --- | --- | --- |
| API Registry | 约束审查、导出和写回所需的官方方法 | 约束学习证据读取方法 |
| 身份守卫 | 防止对错误工程、页面或 PCB 操作 | 防止图片、选区和讲解上下文错页 |
| 页面导航 | 多图页审查和跨页证据采集 | 为指定页面准备官方证据；不隐式切页 |
| 证据封存 | 支撑审查、BOM、DRC 和发布门禁 | 支撑可追溯的硬件讲解 |
| BOM/网表/拓扑 | 支撑设计判断和器件决策 | 支撑器件解释、信号追踪和方案比较 |
| 生命周期状态 | 决定当前可推进的设计阶段 | 保存学习会话与设计上下文的关联 |

## 快速开始

### 安装 Gateway

仓库包含固定 commit 的上游 Git submodule，请递归克隆：

```bash
git clone --recursive https://github.com/Lyyyy212/ZhiYuanEDA.git
cd ZhiYuanEDA
python -m pip install ./packages/easyeda-gateway
python -m easyeda_gateway --version
```

环境要求：Python 3.11+、Node.js 18+、嘉立创EDA专业版，以及官方
[Run API Gateway](https://jlc-ext.com/item/oshwhub/run-api-gateway) 扩展。

### 连接并确认身份

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py start-bridge
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py discover
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py windows
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py export-capabilities
```

`discover` 会扫描 `49620-49629` 并验证服务标识为 `easyeda-bridge`；`windows` 返回后续操作
需要绑定的窗口、工程 UUID 和当前文档 UUID。

### 初始化设计链

```bash
python skills/easyeda-hardware-lifecycle/scripts/workbench.py init --project <project-directory> --name demo
python skills/easyeda-hardware-lifecycle/scripts/workbench.py scaffold --project <project-directory> --stage concept
python skills/easyeda-hardware-lifecycle/scripts/workbench.py status --project <project-directory>
```

### 启动学习画板开发环境

```bash
cd integrations/jlc-hardware-learning-plugin
npm ci
npm run quality
npm run dev
```

学习插件的安装、数据目录和开发说明见
[`integrations/jlc-hardware-learning-plugin/README.md`](integrations/jlc-hardware-learning-plugin/README.md)。

## 安全边界

- 默认只读；所有实时操作都应绑定明确的工程和文档 UUID。
- 页面切换属于 `EPHEMERAL_NAVIGATION`，不保存、不关闭页面，也不修改文档内容。
- 普通业务模块不能提交任意 JavaScript，只能使用锁定的官方方法或固定模板。
- BOM 持久回填只允许 `Manufacturer`、`Manufacturer Part`、`Supplier`、`Supplier Part`。
- Bridge 超时不自动重试；EDA 内部操作可能在 HTTP 超时后仍继续执行。
- 未完成资格验证的导出组合会在调用前拒绝；EPRO 图像路线为 `DISABLED_BY_POLICY`。
- DRC 零错误、DFM 通过、导出成功或证据一致都不等于可制造性和量产批准。

发现安全问题时请遵循 [`SECURITY.md`](SECURITY.md)，不要在公开 Issue 中上传真实工程、
UUID、BOM、网表、截图、Bridge 日志、凭据或本地绝对路径。

## 上游能力移植

已受控适配的固定源码来源包括 Netlist Explorer、Export Design Report、BOM Compare、
Interactive HTML BOM、JLC PCB DFM、PCB to SVG、GenCAD、AI Device Standardization 和
EasyEDA API Skill。

每个仓库的锁定 commit、参考文件、许可证与移植边界见
[`MIGRATION_SOURCES.md`](packages/easyeda-gateway/MIGRATION_SOURCES.md)、
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 和
[`materials/manifests/sources.lock.json`](materials/manifests/sources.lock.json)。

## 目录结构

```text
ZhiYuanEDA/
├─ packages/easyeda-gateway/                  # 受控 API、导航、导出、PCB/BOM 与证据模块
├─ skills/easyeda-hardware-lifecycle/         # 设计链与学习链编排器
├─ integrations/jlc-hardware-learning-plugin/ # 学习画板、MCP 和本地存储
├─ materials/manifests/                       # API 清单、来源锁和集成配置
├─ materials/contracts/                       # 生命周期与学习数据契约
├─ materials/references/                      # 架构、边界和开发规格
├─ materials/sources/                         # 固定版本的上游子模块与 API 类型
├─ examples/api-plans/                        # 只读 API 计划示例
└─ scripts/release/                           # GitHub 发布与许可证检查
```

## 兼容性标识

公开展示品牌为 ZhiYuanEDA。以下既有技术标识继续保留，避免破坏安装脚本、本地证据和学习数据：

- Python 分发包：`easyeda-workbench-gateway`
- Python 模块与 CLI：`easyeda_gateway` / `easyeda-gateway`
- 本地状态目录：`.easyeda-hardware-workbench/`
- Schema 与 API 契约中的既有 `easyeda.*` 标识

## 验证与发布状态

GitHub Actions 会执行 Gateway 单元测试、wheel 许可证检查、生命周期测试、学习契约校验、
插件冷安装探测和 MCP 探测。离线测试只证明代码、契约和发布包一致；真实 EasyEDA 验收
仍需连接官方 Bridge，并记录操作前后的工程与文档身份。

- Gateway：`0.8.0`。
- 硬件学习插件：`0.1.3`。
- GitHub 源码发布：已就绪，默认分支为 `main`。
- 嘉立创EDA拓展广场：当前仓库不是可直接安装的 `.eext` 包；上架版本仍需单独制作、签名和真实环境验收。

参与贡献前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)，版本变化见
[`CHANGELOG.md`](CHANGELOG.md)，发布步骤见 [`PUBLISHING.md`](PUBLISHING.md)。

## 许可证

Lyyyy 原创部分采用 [PolyForm Noncommercial 1.0.0](LICENSE)，禁止商业使用。
由于这一限制，本项目属于 **source-available**，而不是 OSI 定义的开源软件。

第三方子模块、运行时和硬件学习组件继续遵循各自许可证。特别注意：当前 tldraw 条款
不允许在没有相应授权的情况下用于生产环境；详见
[`LICENSE_SCOPE.md`](LICENSE_SCOPE.md) 和 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
