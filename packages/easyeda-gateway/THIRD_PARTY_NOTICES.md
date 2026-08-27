# Third-party notices for easyeda-workbench-gateway

The first-party gateway code is licensed under
`PolyForm-Noncommercial-1.0.0`. The following packaged browser runtimes contain
third-party code under separate terms:

| Packaged file | Primary upstream | Revision | License |
| --- | --- | --- | --- |
| `easyeda_gateway/official_runtime/dfm-checker.min.js` | `easyeda/eext-jlc-order-dfm-checker` | `afd538786d510f537ad4fa47c6329e6a99dc7625` | Apache-2.0; bundled JSZip under MIT |
| `easyeda_gateway/official_runtime/manufacturing-svg.min.js` | `easyeda/eext-export-pcb-to-svg` | `f68898d18c8279e2aaf84a5b2ff07969ebeb005e` | Apache-2.0; bundled JSZip and tracespace packages under MIT |
| `easyeda_gateway/official_runtime/gencad-export.min.js` | `easyeda/eext-export-gencad` | `aba4dff5b0fb8e1c5ad8288b07eb56b01dd0ab9e` | Apache-2.0; bundled JSZip under MIT |

The gateway wrappers change the upstream runtime environment by replacing UI,
download, logging, and extension-storage side effects with fixed guarded
adapters. Source revisions, build parameters, hashes, and modification scope are
documented in `MIGRATION_SOURCES.md` in the source distribution.

Full applicable terms are included in `LICENSES/`:

- `Apache-2.0.txt`
- `JSZip-MIT.txt`
- `tracespace-MIT.txt`

pypdf is a separately installed dependency under BSD-3-Clause and is not copied
into this distribution.
