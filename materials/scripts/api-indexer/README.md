# EasyEDA 官方 API 索引生成器

该模块只读取 `materials` 中已锁定的官方资料快照，不联网、不连接 EasyEDA，也不执行任何工程写操作。

## 输入

- `manifests/sources.lock.json`：版本、提交、哈希和仓库清单。
- `sources/packages/.../index.d.ts`：API 签名真源。
- `sources/core/easyeda-api-skill/references/`：官方说明文档链接。
- `sources/core/`、`sources/examples/`：官方源码和示例调用。

## 输出

- `manifests/api-manifest.json`：类、方法、参数、返回值、枚举、接口、类型别名和 `eda` 运行时模块映射。
- `manifests/api-example-index.json`：`eda.<module>.<method>()` 到官方文件、行号和固定提交的反向索引。
- `references/api-index-summary.md`：面向开发者的覆盖率和未映射调用摘要。

## 运行

```powershell
cd materials/scripts/api-indexer
npm test
```

生成器使用与官方 `pro-api-sdk` 当前锁文件一致的 TypeScript 5.9.3 编译器 API。为避免资料构建依赖临时网络状态，精简运行时已随模块固定在 `vendor/package/lib/typescript.js`；同目录保留原始 `typescript-5.9.3.tgz`，其 SHA-512 必须与官方 SDK 锁文件的完整性值一致：

```text
sha512-jl1vZzPDinLr9eUt3J/t7V6FgNEw9QjvBPdysz9KfQDD41fQrC2Y4vKQdiaUpFT4bXlb1RHhLpp8wtm6M5TgSw==
```

生成结果中的 `generatedAt` 取自资料锁文件，输入不变时输出字节保持稳定。
