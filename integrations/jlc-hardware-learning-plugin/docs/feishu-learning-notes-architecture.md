# 飞书硬件学习笔记架构

## 目标

飞书中的一级分类使用项目名称，底层使用稳定项目标识。一个画板图页对应一个长期维护的飞书图页笔记，学习框编号只在该图页内生效，对话通过 `questionId + canvasPageId + frameNumbers` 与笔记建立不可歧义的绑定。

## 分层

```text
Codex 正常对话 / JLC Hardware Learning 画板
                  |
                  v
      Feishu note domain contracts
      - note-model.mjs
      - project-homepage.mjs
      - page-content.mjs：模块索引/问答受管块模型与局部补丁
      - dialogue-records.mjs：持久化 question/run/answer 读取与摘要校验
      - sync-plan.mjs
      - storage.mjs
                  |
                  v
      Feishu read adapter
      - lark-cli-adapter.mjs：固定命令、user 身份、JSON 成功判定
      - document-inspection.mjs：outline + full 双读取、修订一致性
      - legacy-migration.mjs：旧绑定迁移预览、复用两个 board_token
                  |
                  v
      Confirmed migration adapter
      - lark-cli-adapter.mjs：计划指纹/修订门控和固定写命令
      - confirmed-migration.mjs：Wiki 目录、Docx 迁移、局部正文同步
      - Wiki/Docs/Whiteboard fresh read：逐项验证后原子保存注册表
                  |
                  v
      Confirmed continuous sync
      - confirmed-sync.mjs：精确补丁、完整修订映射、受管块回读验证
      - 仅修改 JLC 受管区；保留用户正文和两个原 board_token
```

领域层不得直接调用 `lark-cli`、HTTP 或飞书 OpenAPI。传输适配器只接受领域层产生的同步计划，并且必须显式使用用户身份、写前确认、稳定幂等键和写后重新读取验证。

## 目录规则

```text
硬件学习笔记
└─ <项目名称>〔同名时追加稳定短标识〕
   ├─ [项目主页正文中的分类标题]
   │  ├─ 00 项目总览
   │  ├─ 01 方案设计
   │  ├─ 02 模块详细设计
   │  ├─ 03 原理图学习
   │  ├─ 04 原理图检查
   │  ├─ 05 BOM与器件选型
   │  ├─ 06 调试与实验记录
   │  └─ 99 历史归档
   └─ <图页序号> <原理图图页名称>  [真实原理图页才单独创建 Docx]
```

`00..99` 是项目主页内的标题，不是 Wiki 子节点，也不会各自产生一个空 Docx。项目名称和图页名称只用于展示。项目以 `projectId/projectUuid` 识别，图页以 `canvasPageId` 识别，并可附加官方 EasyEDA `schematicPageUuid`。同名项目和同名图页不得合并。

稳定标识只属于内部注册表、同步计划、节点属性和验证证据。读者可见的标题、正文、提示框、图片说明、表格与思维导图只显示项目名、图页名和内容名称，不显示项目、图页、画板或图片绑定 ID；隐藏显示不得删除或弱化内部绑定。

## 图页笔记规则

每个项目主页复用一个 `projectOverviewWhiteboardToken`，该工程总画板覆盖工程内全部真实原理图页。每个图页笔记只复用一个 `docToken` 和一个图页学习画板 `whiteboardToken`；同一原理图页上的多个模块和学习框共用该画板。后续同步必须按已验证的 `schematicPageUuid` 分类，禁止按模块重复建板，也禁止用新空画板替换现有画板。旧版 `moduleIndexWhiteboardToken` 仅迁移为遗留资源保留。图页文档建议包含：

1. 原理图学习画板；
2. 学习框模块索引；
3. 对话与学习结论；
4. 待解决问题；
5. 来源版本和同步记录。

学习框状态使用 `unstarted / learning / question-open / concluded / review-required`。一个问题可以关联同页多个学习框，但不能跨图页绑定。

图页学习画板使用统一学习框样式：框线和编号色块透明度均为 50%，边框宽度缩放为 50%；编号使用固定圆角矩形角标（约 `29.2544 × 28.41494`，字号 12，固定偏移 `-8/-8` 压在框的左上角）。原理图缩放时，学习框按图片变换映射，但编号牌尺寸、字号和角标偏移绝不参与缩放。模块颜色没有语义绑定，从柔和候选色中按图页稳定随机分配；同页多个模块在候选色用完前不得重复。模块标签和一句话总结分支直接位于该图页学习画板，并跟随同号学习框颜色。完整执行和验收合同见 `skills/jlc-hardware-learning/references/feishu-learning-note-standard.md`。

## 本地注册表

注册表位于：

```text
<projectDir>/.easyeda-hardware-workbench/learning/feishu-learning-note-registry.json
```

它保存 Wiki 空间、项目节点、项目主页模板/索引摘要、章节标题块、图页 Docx、画板 token、学习框索引和对话绑定。章节条目不得保存独立 Wiki/Docx 节点；旧版章节节点绑定在紧凑模式确认后会被清空。每个图页还保存模板版本、受管内容版本及已同步内容摘要；只有受管模块索引与问答区的摘要均与当前本地模型一致，才认为正文已同步。注册表使用原子替换写入，线上飞书写入成功并完成 fresh read 验证后才能更新对应 token。

## 同步安全边界

- 默认 `--as user`，不使用 bot 身份猜测用户个人知识库。
- 只读识别仅允许固定的 `docs +fetch` 命令，Windows 下直接执行已安装 CLI 的 JavaScript 入口，不经过 shell，也不接受任意 argv。
- 同步计划声明 `wiki.node.ensure`、`wiki.document.move`、`doc.project-overview-whiteboard.ensure`、`doc.project-homepage.ensure`、`doc.whiteboard.ensure` 等逻辑动作；工程总画板动作携带全部原理图页清单，图页画板动作携带唯一原理图页身份，不再声明新建模块索引画板。`doc.project-homepage.ensure` 只增补缺失分类、工程总画板和图页索引，不覆盖用户笔记。实际写命令只能由确认后的传输适配器实现。
- `execute_feishu_learning_note_migration` 必须同时收到 `confirmed=true`、精确 `planFingerprint` 和预览时的文档修订号；适配器会重新计算计划哈希，任一不一致都在首个远端写入前停止。
- 持续同步先调用 `preview_feishu_learning_note_sync`。预览会重新读取项目主页和每个目标图页 Docx，校验工程总画板与对应图页学习画板 token，核对学习框的 `schematicPageUuid` 归属，加载已明确绑定的持久化问答记录，并返回精确 `block_insert_after` / `block_replace` 补丁、完整 `expectedDocumentRevisions` 与计划指纹；预览不写本地或远端。
- `execute_feishu_learning_note_sync` 只接受 `confirmed=true`、该次预览的精确 `planFingerprint` 和完整修订映射。模块索引与问答分别使用带内容摘要的 JLC 受管区；首次插入后，后续只替换这两个受管范围，不覆盖画板或用户维护的其他块。
- 在任何图页正文同步前，必须存在与注册表项目一致的官方 EasyEDA `schematicPageUuid`。`bind_feishu_page_identity_from_learning_evidence` 只在注册表全部学习框都关联同一官方原理图页时写入本地绑定，绝不根据标题猜测。
- `link_feishu_learning_dialogue_from_record` 从本地 question/run/answer 三类持久化记录读取问题、学习框、问题摘要和回答摘要；帧号、页面或摘要不一致时停止，不从聊天窗口抓取内容。
- 迁移编排只调用固定的 Wiki/Docs 命令，不接受任意 argv，不通过 shell；节点按标题只复用唯一精确匹配，重复同名节点会停止而不是猜测。
- 所有写入先展示准确范围并取得确认。
- 用户确认应绑定同步计划的 `planFingerprint`；计划内容或目标修订变化后必须重新预览和确认。
- 同一逻辑动作重试必须复用同一个幂等键。
- 写入后重新读取节点、文档或 `board_token` 验证。
- 不抓取历史 Codex UI；只消费已持久化的学习问题和对话记录。
- 飞书同步不授权保存或修改 EasyEDA 工程。

## 旧笔记迁移

`inspect_feishu_learning_note_target` 对目标 Docx 做两次 fresh read，并提取标题、章节、模块标题、图页学习画板以及可能存在的遗留模块索引画板。`preview_feishu_learning_note_migration` 再校验旧 `learning.lark-binding.v1` 与 `learning.note-package.v1`：工程 UUID、图页 ID、内容摘要、文档 token、图页画板 token 或遗留画板 token 任一不一致都会停止；工程总画板必须单独创建、覆盖全部原理图页并绑定后才能执行迁移。

迁移预览不会写本地或飞书。当前旧笔记是 Drive Docx 时，同步计划使用 `wiki.document.move` 把这份原文档直接迁入 `硬件学习笔记 / <项目名称> / <图页>`，不会复制新文档；`03 原理图学习` 只是项目主页中的分类标题和图页索引。移动和正文更新必须在用户确认精确动作清单后执行，并在成功后重新读取再写入本地注册表。

确认执行后，编排器按浅到深创建或复用根节点、项目节点和真实图页节点，迁移原 Docx，增补项目主页分类/索引，并只对旧品牌词和工程/图页身份做 `str_replace` 局部更新。每次正文写入都使用 fresh revision；最终再次核对项目主页、图页章节、模块编号和两个原始 `board_token`，然后一次性写入本地注册表。中途失败不写注册表；重跑时已创建节点和已迁入的 Docx 会按稳定 token 复用。

初始迁移不会把旧模块标题伪装成已完成的持续同步。迁移后第一次持续同步会建立两个受管区；只有这一步完成 fresh read 验证后，注册表才记录 `managedContentVersion` 和 `syncedContentDigest`。
