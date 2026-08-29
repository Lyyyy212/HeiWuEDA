# 黑五画板

面向 Codex 的独立黑五画板插件。它以官方 EDA Bridge 导出的 PNG 或本地渲染的 PDF 页面作为视觉证据，支持框选原理图区域、在正常对话栏提问、接收教学标注、管理多个画板和图页，以及导出 PNG、SVG 和 JSON。

该插件不生成图片，不上传遥测数据，也不直接写入 EasyEDA 工程。EasyEDA 访问始终由硬件生命周期层通过官方 `eda.*` API 以只读方式完成。

## 组成

- Plugin：`jlc-hardware-learning`
- Skill：`$jlc-hardware-learning`
- MCP server：`jlc_hardware_learning_mcp`
- Widget：`黑五画板`

## 开发与验证

```powershell
npm install
npm run build:artifacts
npm run quality
```

发布产物位于 `mcp/generated/`。插件和 Skill 还应分别通过 Codex Plugin Creator 与 Skill Creator 的校验脚本。

## 项目数据

原有默认画板继续保存在当前项目的 `canvas/` 目录。新增画板使用稳定 UUID 存放在 `canvases/` 下，当前活动画板记录在 `canvases/manifest.json`；删除的非默认画板会移动到项目内回收目录，不直接清除：

```text
canvas/
  hardware-learning-selection.json
  hardware-learning-view-state.json
  pages/
    manifest.json
    <page-id>/
      hardware-learning-canvas.json
      assets/
canvases/
  manifest.json
  <canvas-uuid>/
    hardware-learning-selection.json
    hardware-learning-view-state.json
    pages/
  .trash/
    <canvas-uuid>-<timestamp>/
```

每个画板均可新建、重命名和切换图页。至少保留一个图页；删除图页会进入画布撤销历史。默认画板不可删除，避免破坏旧版本数据和已有工作流。

旧画板的文件名和元数据仅作为一次性兼容输入读取；下一次保存会使用新的 `hardware-learning-*` 文件名和 `hardwareLearning*` 元数据。

## 飞书学习笔记（开发分支）

飞书功能使用“项目名称展示、稳定项目 ID 绑定、一个画板图页对应一个飞书图页笔记”的模型。领域契约位于 `mcp/feishu/`，目录与同步边界见 `docs/feishu-learning-notes-architecture.md`。`get_feishu_learning_note_state` 用于只读预览目录和同步计划，`update_feishu_learning_note_state` 只登记经过线上回读验证的本地绑定。领域层不直接调用飞书 API；后续传输适配器负责 Wiki 节点、Docx 正文、已有画板 token 和跨项目 Base 索引，并遵守写前确认、幂等重试与写后回读验证。

## 环境变量

- `JLC_HARDWARE_LEARNING_PLUGIN_ROOT`：插件根目录。
- `JLC_HARDWARE_LEARNING_PROJECT_DIR`：画板所属项目目录。
- `JLC_HARDWARE_LEARNING_CANVAS_DIR`：画板数据目录，默认 `<projectDir>/canvas`。
- `JLC_HARDWARE_LEARNING_PORT`：本地开发服务器端口，默认 `43217`。

本仓库保留原始 MIT 许可证文本及 Git 历史，以满足已有开源代码的许可证要求；用户可见产品名称为黑五画板，技术插件 ID 与 MCP 工具名继续使用 `jlc-hardware-learning` 以保持兼容。
