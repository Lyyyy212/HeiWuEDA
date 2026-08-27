# Official page and board-document navigation

Use this adapter when a lifecycle consumer must list, activate, or traverse
pages in the currently active EasyEDA schematic. It changes editor focus only;
it never changes schematic content and never saves.

Use the separate board-document operation when a consumer must move between a
board-associated schematic page and PCB in the same already-open project. It
uses exact UUIDs, never opens another project, and never saves either document.

## Fixed official API surface

The gateway owns all executable code and permits only:

- `DMT_Project.getCurrentProjectInfo#1`;
- `DMT_SelectControl.getCurrentDocumentInfo#1`;
- `DMT_EditorControl.openDocument#1`;
- `DMT_EditorControl.activateDocument#1`.

Board-document navigation additionally permits the read-only
`DMT_Board.getAllBoardsInfo#1` inventory call. Only documents returned under a
board whose project UUID matches the active project may be selected. Supported
targets are schematic pages (`documentType=1`) and PCBs (`documentType=3`).

The project tree supplies ordered `IDMT_SchematicPageItem` records. The adapter
selects the one schematic that contains the active page, so same-named pages or
references in other schematics cannot be mixed. It never calls project-open,
document-close, document-save, primitive mutation, visual export, or arbitrary
JavaScript.

## Operations

`schematic-pages` is `READ`. It lists page UUID, name, owning schematic UUID and
order, then proves that project/page identity did not change.

`schematic-page-activate` is `EPHEMERAL_NAVIGATION`. It requires exact project
and origin-page UUIDs, rejects a target outside the current schematic, opens and
activates the target tab, verifies the live target UUID, and intentionally
leaves that page active. If activation fails after changing focus, it attempts
to restore and verify the origin tab before returning failure.

`schematic-page-traverse` is `EPHEMERAL_NAVIGATION`. It requires exact project
and origin-page UUIDs, visits every ordered page with an identity check after
each activation, and always attempts to restore the original tab. It passes only
when restoration is verified.

```powershell
py scripts/easyeda_gateway.py schematic-pages --evidence-dir <evidence>
py scripts/easyeda_gateway.py schematic-page-activate --page-uuid <target> --project-uuid <project> --document-uuid <origin> --evidence-dir <evidence>
py scripts/easyeda_gateway.py schematic-page-traverse --project-uuid <project> --document-uuid <origin> --evidence-dir <evidence>
py scripts/easyeda_gateway.py board-documents --project-uuid <project> --document-uuid <origin> --evidence-dir <evidence>
py scripts/easyeda_gateway.py board-document-activate --target-uuid <target> --target-document-type <1-or-3> --project-uuid <project> --document-uuid <origin> --evidence-dir <evidence>
```

Use a freshly listed UUID. A page name is only a display label; if multiple
pages share it, require the UUID or another unambiguous user choice.

`board-documents` is `READ` and preserves the current identity.
`board-document-activate` is `EPHEMERAL_NAVIGATION`: it requires exact project,
origin-document, target-document, and target-type guards; verifies the target
after activation; and leaves the requested target active. If activation fails
after focus may have changed, it attempts to restore the original tab and
records whether restoration succeeded. Consumers that temporarily select a PCB
must explicitly navigate back to the captured origin UUID in `finally`.

## Failure and consumer rules

- Do not retry automatically.
- A transport timeout means the active page is unknown. Re-probe identity before
  any read, export, write plan, or further navigation.
- Cross-page consumers must bind every artifact and reference to its owning page
  UUID and restore the origin page in `finally`.
- Navigation does not make `current-schematic` PNG/PDF an exact active-page
  artifact. The known-hanging `current-page` visual export remains blocked.
- Learning mode may navigate only on explicit user request; opening JLC Hardware Learning,
  importing an image, or asking a question is not navigation authorization.
