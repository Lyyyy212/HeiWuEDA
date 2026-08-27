# Publishing profile

## Confirmed identity

- Copyright holder: `Lyyyy`
- Developer and publisher display name: `Lyyyy`
- Product display name: `ZhiYuanEDA`
- Repository name: `ZhiYuanEDA`
- Python package: `easyeda-workbench-gateway`
- First-party license: `PolyForm-Noncommercial-1.0.0`
- Commercial licensing: not offered

This repository is independently developed. It may be described as suitable
for use with 嘉立创EDA专业版, but must not be presented as an official EasyEDA or
嘉立创 product.

## Public repository boundary

This public tree is generated without the source repository's Git history and
excludes all live `artifacts/`, `evidence/`, backups, runtime state, project
UUIDs, page UUIDs, locally exported designs and local absolute paths.

Official EasyEDA repositories remain pinned Git submodules. Clone with
`--recursive`, retain every upstream license, and never replace third-party
license terms with the root noncommercial license.

## GitHub release checklist

1. Run the Python, lifecycle and Node.js validation commands in `README.md`.
2. Confirm `git status --short` is clean.
3. Run `node materials/scripts/scan-public-release.mjs` to reject private
   evidence directories, credentials, local paths, tenant URLs and live-looking
   design identifiers.
4. Confirm all Git submodules match `PUBLIC_RELEASE_MANIFEST.json`.
5. Use `main` as the default branch and protect it after creating the remote.
6. Create the first tag only after GitHub Actions passes.

The public hardware-learning copy excludes `docs/evidence/**`. Test-only
Feishu tokens, tenant URLs and project/page identifiers must use explicit
`Fixture*` or reserved zero UUID values while preserving the same behavioral
coverage.

Suggested repository description:

> ZhiYuanEDA: guarded EasyEDA API access and a traceable hardware lifecycle workbench for noncommercial use.

Suggested topics: `easyeda`, `jlc`, `eda`, `pcb`, `schematic`, `hardware-design`,
`bom`, `python`, `noncommercial`.

## EasyEDA Extensions Marketplace

The GitHub repository is not the marketplace artifact. A marketplace candidate
must be built as a dedicated `.eext`, use a store-assigned or newly generated
UUID, and pass the official SDK packaging and live EasyEDA validation flow.

Candidate identity:

```json
{
  "name": "zhiyuaneda-gateway",
  "displayName": "ZhiYuanEDA Gateway",
  "publisher": "Lyyyy",
  "license": "PolyForm-Noncommercial-1.0.0",
  "categories": ["Project", "Other"]
}
```

The source under `integrations/zhiyuaneda-gateway/` is version `0.1.0` and is
a GitHub developer preview. Do not upload that package to the marketplace while
the compatibility `execute` message remains enabled. The marketplace build must
use a fixed audited operation set, include a custom logo/banner and complete a
fresh EasyEDA runtime acceptance pass.
