# 黑五EDA 工作台扩展发布流程

## 不变的商店身份

正式更新必须保留以下字段，任何一个变化都会被视为另一个扩展或被发布检查拒绝：

- `name`: `hardware-workbench`
- `uuid`: `647e863e3bd34060949c51f22d52de05`
- `displayName`: `黑五EDA`
- `publisher`: `Lyyyy`
- `engines.eda`: `~3.2.0`
- `repository`: `https://github.com/Lyyyy212/HeiWuEDA`

锁定值保存在 `release/marketplace-identity.json`。只有嘉立创官方平台明确要求迁移身份时，才允许在单独评审中修改该文件。

公开扩展页固定为 <https://jlc-ext.com/item/lyyyy-212/hardware-workbench>。公开文档只能使用这个不带查询参数的地址，不能提交浏览器复制出的 `jspm`、`jlc_vid`、`code` 等跟踪或会话参数。

用户确认的商店简介、关键词、Logo、功能图和演示截图保存在 `release/marketplace-listing.json`。发布检查会核对素材大小与 SHA-256；以后确实要更新商店详情时，应在同一次评审中更新详情锁和更新记录，不能让普通代码合并静默覆盖。

## 发布一个新版本

1. 选择严格大于已发布版本的新语义化版本号；协议不兼容更新至少提升次版本号。
2. 同步修改 `extension.json`、`package.json`、`package-lock.json` 和工作台页眉版本。
3. 在 `CHANGELOG.md` 顶部增加带日期的版本条目。
4. 运行 `npm ci`，再运行 `npm run quality`。
5. 连续构建两次并核对 SHA-256 完全相同。
6. 在本地嘉立创EDA开发者模式中直接导入新包，确认不需要删除旧版；核对扩展管理器显示的 UUID 与版本。
7. 通过专属 Bridge 重新读取 `/health` 和 `/eda-windows`，确认 `service=easyeda-bridge`、`edaConnected=true`、协议版本和扩展版本匹配。
8. 将 CI 生成的 `.eext` 手工上传到嘉立创官方扩展平台，等待审核后再发布。

官方平台上传和审核不属于 CI 自动化范围。不要让脚本保存账号凭据，也不要把“CI 已构建”描述为“官方商店已发布”。客户端是否自动安装更新，应以正式上架后的实际客户端验证为准。

## 回滚

发布前保留上一版本的 `.eext`、SHA-256 和源代码提交。发现问题时发布更高版本的修复包，不复用或覆盖已经发布的版本号。
