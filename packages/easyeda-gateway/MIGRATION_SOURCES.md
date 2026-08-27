# Official EasyEDA migration sources

本文件锁定首批只读移植所依据的官方 EasyEDA 仓库。上游源码保存在工作台 Git submodule 中；实现只复用读取与分析思路，不暴露任意脚本执行入口，也不保存 EDA 文档。

| 本地能力 | 官方仓库与 commit | 参考路径 | 移植边界 |
| --- | --- | --- | --- |
| 原理图网表分析 | `easyeda/eext-netlist-explorer` `6661961fc8780e13b97a9450a96afbaaf2960bf7` | `src/index.ts`, `iframe/netlist.html` | 网表读取、引脚/网络、连接关系、连接器映射、拓扑与 BOM；只读 |
| PCB 设计报告 | `easyeda/eext-export-design-report` `31a8cfec95bcae13e981b912c6bc86025062dca0` | `src/index.ts` | 图元统计、网络长度、DRC 规则组和近似板框包围盒；不写设计 |
| BOM 比较 | `easyeda/eext-bom-compare` `4489dd9b857e19505a2f5a0dd383342bb77923d6` | `iframe/src/core/comparator.ts`, `column-config.ts`, `column-mapper.ts` | CSV/TSV/TXT/JSON 规范化与差异；暂不含 XLSX UI |
| 交互装配 BOM | `easyeda/eext-interactive-html-bom` `430ea9d06a1c975ed3d2c6da83a6686a1f737084` | `iframe/index.html` | 自包含 `assembly-lite.v1`；搜索、面筛选、完成标记与轻量 SVG，不复刻完整官方几何 |
| JLC PCB DFM | `easyeda/eext-jlc-order-dfm-checker` `afd538786d510f537ad4fa47c6329e6a99dc7625` | `src/index.ts`, `src/dfm/standards.ts` | 源码锁定的 18 项 PCB 检查；UI/日志/扩展存储被代理隔离，只落本地 JSON，不定位或修改图元 |
| 制造 SVG | `easyeda/eext-export-pcb-to-svg` `f68898d18c8279e2aaf84a5b2ff07969ebeb005e` | `src/index.ts`, `src/gerber-render.ts` | 官方 Gerber 读取、分层 SVG 渲染与 ZIP；下载被重定向到不可覆盖证据目录 |
| GenCAD | `easyeda/eext-export-gencad` `aba4dff5b0fb8e1c5ad8288b07eb56b01dd0ab9e` | `src/index.ts`, `src/footprintParser.ts`, `src/footprintExtractor.ts` | GenCAD 1.4 板框、焊盘栈、器件、网络与走线；只读 PCB 与库封装文件 |
| 器件匹配 dry-run | `easyeda/eext-ai-device-standardization` `89abac48075bd4e0ebc2a30bee55939251f8660f` | `iframe/app.js`, `src/bom-service.ts` | 只读元件与官方器件库搜索，复用默认评分；不创建设备、不修改/保存原理图 |
| 本地 Bridge | `easyeda/easyeda-api-skill` `213856a67d0237d7d06c4a5f44c4310ff633e78d` | `scripts/bridge-server.mjs`, `SKILL.md` | 仅 localhost 连接与官方服务握手 |

API 方法签名由 `materials/manifests/api-manifest.json` 锁定：`@jlceda/pro-api-types` `0.4.15`，声明文件 SHA-256 `088146a3e913a7e08c164a4c7c60aae41c0cfecafe18697c68d6aa470ffa4254`。

固定模板只把清单中的 `eda.*` 方法列为可执行依赖。`getState_*` 是官方返回对象的类型接口，不是可由网关直接调度的模块方法；这些访问器写死在模板中，并由上游源码快照和回归测试约束。

## Source-pinned browser bundles

三项 PCB 插件在各自锁定 commit 上用固定 esbuild 参数构建 IIFE 浏览器包，并作为 Python 包数据随网关发布。运行前会再次核对 bundle SHA-256；不匹配则在 Bridge 请求前拒绝。包中的插件下载、UI、日志和配置副作用由固定代理拦截，真正保留的只有清单锁定的读取 API 与一次 `SYS_FileSystem.saveFileToFileSystem#1` 本地证据写入。

## Retained local `$jlc` compatibility capabilities

The integrated export layer also ports the already-tested local `$jlc` workflows for official BOM CSV, JLCEDA netlist, EPRO source capture, strict DRC, and cross-artifact consistency checks. These are retained implementation evidence, not a replacement authority for official API signatures. EPRO parsers remain maintenance code, but EPRO-derived images are disabled by policy and are not accepted as review visuals.
