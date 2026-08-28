# 更新日志

## 0.1.0 - 2026-08-27

### 新增

- 发布 `黑五EDA Gateway` 首个 GitHub 开发预览版本。
- 并行探测 `49620-49629`，缩短本地 Bridge 发现等待时间。
- 增加专属 `gatewayId`、产品标识、WebSocket ID、MessageBus topic 与存储键。
- 兼容官方 `service: "easyeda-bridge"` 握手，可连接现有 黑五EDA Python Gateway。
- 记忆最近一次成功端口，并优先选择声明 黑五EDA 身份的 Bridge。
- 增加有上限的指数退避、抖动和持续重连。
- 连续两次心跳超时后才重新发现连接，减少 EasyEDA 短暂卡顿造成的误重连。
- 菜单提供重新连接、停止连接、切换自动连接和状态查看。
- 构建流程生成 `build/dist/zhiyuaneda-gateway_v0.1.0.eext`。
- 增加专属握手、官方兼容握手和自动连接开关三项运行时测试。

### 发布边界

- 本版本用于 GitHub 源码公开与本地联调，不是嘉立创EDA扩展广场提交包。
- 为兼容现有 Python Gateway，本版本仍支持官方 Bridge 的 `execute` 消息。
- 扩展广场版本必须先改为固定、可审计的操作协议，并补齐商店图标和真实 EasyEDA 验收记录。
