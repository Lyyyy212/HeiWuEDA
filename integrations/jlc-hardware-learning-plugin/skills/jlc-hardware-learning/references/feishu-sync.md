# Feishu learning-note synchronization

Before planning, creating, exporting, migrating, or editing a Feishu hardware-learning note, read [feishu-learning-note-standard.md](feishu-learning-note-standard.md) completely. Treat its project-overview-board contract, one-board-per-schematic-page classification, fixed-size badges, color mapping, confirmation gate, and post-write checks as one versioned standard.

Organize by readable project name but bind by stable `projectId/projectUuid`. One project maps to one project homepage and one reused project-overview whiteboard containing every schematic page. Each verified schematic page maps to one long-lived Docx and one reused page-learning whiteboard. Multiple modules on the same schematic page share that board. Classify every learning frame by its verified `schematicPageUuid`; never use a title, duplicate page name, module name, or frame number alone as identity. Keep internal IDs out of reader-visible text. Do not create a separate board per module or a second module-index board for new notes.

## Existing legacy note

1. Call `inspect_feishu_learning_note_target`; require official user-identity reads and matching outline/full document token and revision.
2. Create or resolve the project-overview board, verify that it contains all project schematic pages, and bind its token. Then call `preview_feishu_learning_note_migration` with the verified EasyEDA project identity, overview-board token, and project directory. It must reuse the existing page Docx/page board, preserve any legacy index board, and report zero writes.
3. Show exact targets and obtain confirmation.
4. Call `execute_feishu_learning_note_migration` only with `confirmed=true`, the exact `planFingerprint`, and `expectedDocumentRevisionId`. It must re-preview, preserve the page board and any legacy board, perform only planned changes, fresh-read verify, and save the local registry only after complete success. Any fingerprint/revision drift requires a new preview and confirmation.

## Continuous synchronization

1. Call `get_feishu_learning_note_state` for a read-only preview. Categories `00..99` are headings inside one compact project homepage; only real schematic pages become child Docx nodes.
2. Use Feishu user identity. Route Wiki nodes through Wiki, Docx through Docs, and existing boards through Whiteboard. Never replace an existing board with a new blank board. Bind the project-overview board separately before marking the homepage synchronized.
3. When page identity is missing, call `bind_feishu_page_identity_from_learning_evidence`. Persist only when all registered frames resolve through saved evidence to one official schematic page in the same project; never infer identity from a title. That verified page identity is the classification key for the page board and every learning frame on it.
4. Link a completed dialogue through `link_feishu_learning_dialogue_from_record`, which verifies saved question/run/answer/response digests rather than scraping chat history.
5. Call `preview_feishu_learning_note_sync` before every write. Show the project-overview board, target page Docx/page-board tokens, frame-to-schematic assignments, managed patches, the complete expected-revision map, blockers, and fingerprint.
6. Only after confirmation call `execute_feishu_learning_note_sync` with the exact fingerprint and revision map. It may change only JLC-managed ranges, must preserve unrelated blocks, the project-overview board, page boards, and legacy boards, fresh-read verify both managed digests, and save the registry once after success.

For independently verified atomic operations, update local bindings only after the remote fresh read succeeds. Supported actions are `initialize`, `bind-root`, `bind-project`, `bind-project-overview-board`, legacy `bind-section`, `bind-page`, `upsert-frame`, `link-dialogue`, `mark-project-homepage-synced`, and `mark-page-synced`; do not use `bind-section` in the compact layout.

The registry is `<projectDir>/.easyeda-hardware-workbench/learning/feishu-learning-note-registry.json`. State tools are local-only; inspect/preview tools may read Feishu; none authorizes a remote write. If authentication, scope, identity, or fresh-read verification is missing, keep the action pending and do not guess a token.
