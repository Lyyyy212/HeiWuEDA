# EasyEDA API 资料来源策略

## 权威等级

### L1：权威签名

来源：`@jlceda/pro-api-types`。

用于确认类、方法、参数顺序、参数类型、返回类型、枚举、接口和类型别名。任何生成的 `eda.*` 调用都必须能映射到固定版本的声明文件。

### L2：权威语义

来源：`https://prodocs.lceda.cn/cn/api/`。

用于确认运行上下文、限制、备注、错误处理、接口稳定性、坐标单位、文档类型和开发阶段标记。网页快照只是取证副本；需要更新时重新下载并比较哈希。

### L3：官方实现

来源：`https://github.com/easyeda` 组织下的 SDK 和扩展仓库。

用于学习真实组合调用、扩展目录、iframe、MessageBus、Bridge、原理图和 PCB 操作模式。示例代码可能包含面向具体扩展的取舍，不能反向覆盖 L1/L2。

### L4：发现参考

来源：`https://jlc-ext.com/` 扩展广场。

用于发现需求、交互形式和社区方案。发布者、版本、许可证和源码状态必须单独核对。第三方示例不能作为 API 存在性、签名或生产写入安全性的证明。

### I1：第三方界面集成

来源：固定提交和许可证的 JLC Hardware Learning 等第三方 UI 项目。

只用于画板交互、选区、标注和本地会话持久化，不进入 L1-L3 的 EasyEDA API 权威链。第三方界面不能直接持有 EasyEDA Bridge、定义 `eda.*` 签名或把画板意图解释为工程写入授权。具体快照见 [`../manifests/integrations.lock.json`](../manifests/integrations.lock.json)。

## 运行时规则

- 未在固定类型声明或官方参考中出现的方法，不调用。
- 调用前读取完整签名、枚举、接口、返回值和备注。
- 原理图、PCB 和系统 API 分域；操作前验证工程、页面 UUID 和文档类型。
- 读操作、未保存写入、保存写入分级管理。
- 官方示例中的删除、重建、`setDocumentSource` 或自动执行逻辑默认视为高风险研究材料。
- 资料快照的更新不等于本机 Skill、Bridge 或 EasyEDA 扩展已升级。
- 学习画板中的修改建议、框选和提问均不构成 EasyEDA 写回授权。
- JLC Hardware Learning 学习模式不得调用生图、按标注改图、AI HTML 或 AI Slides 能力。
