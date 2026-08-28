# 黑五EDA Gateway

这是 黑五EDA 自有的嘉立创EDA专属网关扩展源码，不直接修改
`materials/sources/core/eext-run-api-gateway` 中锁定的官方上游子模块。
扩展使用独立的产品名、UUID、WebSocket ID、MessageBus topic 和存储键，
但仍兼容官方 `service: "easyeda-bridge"` 协议，因此可以和工作台现有的
Python 受控网关一起工作。

## 连接优化

- 并行探测 `49620-49629`，避免串行等待最长 35 秒。
- 记住上次成功端口，专属 Bridge 与通用 Bridge 同时存在时优先专属实例。
- 失败后持续重试，采用 `1s -> 2s -> 4s -> 8s -> 15s` 有上限退避和小幅抖动，
  不再在 5 轮后永久停止。
- 单端口握手窗口放宽到 3.5 秒。
- 连续两次心跳超时才触发重连，减少嘉立创EDA短暂卡顿导致的抖动。
- “切换自动连接”会立即更新运行时状态，而不是只修改下次启动的配置。
- 状态窗口显示连接模式、重试次数、下次重试和最后错误。

## 开发构建

```powershell
npm install
npm run quality
```

开发包输出到：

```text
build/dist/zhiyuaneda-gateway_v0.1.0.eext
```

`extension.json` 中的 UUID 是本地开发 UUID，没有复用官方 Run API Gateway 的 UUID。
正式上架前必须使用官方 SDK/扩展商店流程分配或确认正式 UUID。

## 发布边界

当前 `0.1.0` 是 GitHub 开发预览与本地联调候选包，不是商店发布包。为了兼容现有工作台，
它仍实现官方 Bridge 的 `execute` 消息。按项目现有发布政策，嘉立创EDA
商店的首个版本不能公开任意代码执行入口；需要在商店构建配置中改为固定、
可审计的只读/短暂导航操作集，并通过发布检查后才能上传。

连接状态不授权修改或保存 EDA 设计。实际业务调用仍由
`packages/easyeda-gateway` 验证锁定 API manifest、项目/图页身份和风险等级。

## 来源与许可

连接协议和扩展运行时模式派生自
`easyeda/eext-run-api-gateway@479d9b3e58d105229dc00f914c0871700a9f04df`（Apache-2.0）。
项目原创修改遵循根目录 `LICENSE` 和 `LICENSE_SCOPE.md`。构建器会把根许可、
NOTICE、第三方通知和 Apache-2.0 文本一起放入 `.eext`。
