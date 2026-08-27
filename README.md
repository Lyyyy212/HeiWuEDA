# EasyEDA Hardware Workbench

> 个人开发者：**Lyyyy**。本项目自研部分依据
> `PolyForm-Noncommercial-1.0.0` 公开源码，仅允许非商业用途，不提供商业授权。
> 第三方代码继续遵循其原始许可证；详见 [`LICENSE_SCOPE.md`](LICENSE_SCOPE.md)
> 和 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。本项目不是嘉立创EDA官方产品。

这是面向 GitHub 发布的净化版本，不包含本地工程、现场证据、备份、账号信息或 EasyEDA 项目数据。项目提供以下相互隔离的能力：

- `packages/easyeda-gateway/`：受控的 EasyEDA 官方 Bridge/API 适配层。
- `skills/easyeda-hardware-lifecycle/`：`concept -> module_design -> schematic_review -> bom_selection -> bom_writeback` 五阶段硬件工作流。
- `integrations/jlc-hardware-learning-plugin/`：本地硬件学习画板和 MCP 集成。
- `materials/`：API 清单、契约、来源锁和固定版本的官方参考子模块。

## 安全边界

- 默认只读；页面切换属于临时 UI 状态，必须绑定明确的工程和页面 UUID，并恢复原页面。
- 普通业务模块不能提交任意 JavaScript，只能调用锁定清单中的官方 `eda.*` 方法。
- BOM 持久回填只允许 Manufacturer、Manufacturer Part、Supplier、Supplier Part 四个采购字段，并要求独立授权、验收与回读。
- Bridge 超时不会自动重试，因为 EasyEDA 内部操作可能仍在执行。
- DRC 零错误、导出成功或证据一致都不等同于可制造性批准。

## 环境要求

- Python 3.11+
- Node.js 18+
- 嘉立创EDA专业版及官方 Run API Gateway 扩展
- 需要启动 Bridge 时，安装官方 `easyeda-api` Skill 及其 Node.js 依赖

官方扩展参考：[Run API Gateway](https://jlc-ext.com/item/oshwhub/run-api-gateway)

克隆时需要拉取锁定的上游子模块：

```bash
git clone --recursive <repository-url>
cd easyeda-hardware-workbench
```

## 安装

```bash
python -m pip install ./packages/easyeda-gateway
python -m easyeda_gateway --version
```

查看 Bridge 和导出能力：

```bash
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py discover
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py windows
python skills/easyeda-hardware-lifecycle/scripts/easyeda_gateway.py export-capabilities
```

初始化一个独立的硬件生命周期工程：

```bash
cd skills/easyeda-hardware-lifecycle/scripts
python workbench.py init --project <project-directory> --name demo
python workbench.py scaffold --project <project-directory> --stage concept
python workbench.py status --project <project-directory>
```

底层命令和移植能力详见 [`packages/easyeda-gateway/README.md`](packages/easyeda-gateway/README.md)。

## 离线验证

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
python -m pip wheel --no-deps --wheel-dir dist ./packages/easyeda-gateway
python scripts/release/verify_wheel.py dist/easyeda_workbench_gateway-0.8.0-py3-none-any.whl
```

这些测试只证明离线代码、契约和发布包的一致性。真实 EasyEDA 验收必须连接官方 Bridge，记录前后工程/文档身份，并遵守只读和显式授权边界。

## 许可证

Lyyyy 原创部分采用 [PolyForm Noncommercial 1.0.0](LICENSE)，禁止商业使用。由于该限制，本项目是 source-available，而不是 OSI 定义的开源软件。

第三方子模块、运行时和硬件学习组件分别保留 Apache-2.0、MIT、BSD-3-Clause、tldraw 等原始条款。特别注意：当前 tldraw 许可证不允许在没有相应授权的情况下用于生产环境，详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 发布状态

当前目录是 GitHub 源码发布候选，不是嘉立创EDA拓展广场的 `.eext` 安装包。拓展广场版本需要单独制作、签名和验证。
