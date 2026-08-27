# JLC Hardware Learning

面向 Codex 的独立硬件学习画板插件。它以官方 EasyEDA 导出的 PNG 或本地渲染的 PDF 页面作为视觉证据，支持框选原理图区域、在正常对话栏提问、接收教学标注、切换画板图页，以及导出 PNG、SVG 和 JSON。

该插件不生成图片，不上传遥测数据，也不直接写入 EasyEDA 工程。EasyEDA 访问始终由硬件生命周期层通过官方 `eda.*` API 以只读方式完成。

## 组成

- Plugin：`jlc-hardware-learning`
- Skill：`$jlc-hardware-learning`
- MCP server：`jlc_hardware_learning_mcp`
- Widget：`JLC Hardware Learning Canvas`

## 开发与验证

```powershell
npm install
npm run build:artifacts
npm run quality
```

发布产物位于 `mcp/generated/`。插件和 Skill 还应分别通过 Codex Plugin Creator 与 Skill Creator 的校验脚本。

## 项目数据

画板数据默认保存在当前项目的 `canvas/` 目录：

```text
canvas/
  hardware-learning-selection.json
  hardware-learning-view-state.json
  pages/
    manifest.json
    <page-id>/
      hardware-learning-canvas.json
      assets/
```

旧画板的文件名和元数据仅作为一次性兼容输入读取；下一次保存会使用新的 `hardware-learning-*` 文件名和 `hardwareLearning*` 元数据。

## 环境变量

- `JLC_HARDWARE_LEARNING_PLUGIN_ROOT`：插件根目录。
- `JLC_HARDWARE_LEARNING_PROJECT_DIR`：画板所属项目目录。
- `JLC_HARDWARE_LEARNING_CANVAS_DIR`：画板数据目录，默认 `<projectDir>/canvas`。
- `JLC_HARDWARE_LEARNING_PORT`：本地开发服务器端口，默认 `43217`。

本仓库保留原始 MIT 许可证文本及 Git 历史，以满足已有开源代码的许可证要求；产品名称、工具名、Skill 和用户界面均使用 JLC Hardware Learning 身份。
