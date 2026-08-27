# Third-party notices

This file records the main third-party works referenced or distributed by
EasyEDA Hardware Workbench. It does not replace the corresponding license text.
Pinned source revisions are also recorded in `.gitmodules`,
`materials/manifests/sources.lock.json`, and
`packages/easyeda-gateway/MIGRATION_SOURCES.md`.

## EasyEDA extension sources

The following source-pinned projects are licensed under Apache License 2.0 by
their respective copyright holders:

| Component | Pinned revision | Local use |
| --- | --- | --- |
| `easyeda/eext-run-api-gateway` | `479d9b3e58d105229dc00f914c0871700a9f04df` | Official bridge extension reference |
| `easyeda/pro-api-sdk` | `874bd9d311e8d4d6f7f6c7cf887751db8fb47ac1` | Extension SDK and packaging reference |
| `easyeda/eext-jlc-order-dfm-checker` | `afd538786d510f537ad4fa47c6329e6a99dc7625` | Source-pinned DFM runtime |
| `easyeda/eext-export-pcb-to-svg` | `f68898d18c8279e2aaf84a5b2ff07969ebeb005e` | Manufacturing SVG runtime |
| `easyeda/eext-export-gencad` | `aba4dff5b0fb8e1c5ad8288b07eb56b01dd0ab9e` | GenCAD runtime |
| `easyeda/eext-netlist-explorer` | `6661961fc8780e13b97a9450a96afbaaf2960bf7` | Netlist analysis reference |
| `easyeda/eext-export-design-report` | `31a8cfec95bcae13e981b912c6bc86025062dca0` | PCB report reference |
| `easyeda/eext-bom-compare` | `4489dd9b857e19505a2f5a0dd383342bb77923d6` | BOM comparison reference |
| `easyeda/eext-interactive-html-bom` | `430ea9d06a1c975ed3d2c6da83a6686a1f737084` | Interactive BOM reference |
| `easyeda/eext-ai-device-standardization` | `89abac48075bd4e0ebc2a30bee55939251f8660f` | Device-match scoring reference |

The complete Apache-2.0 texts remain in the corresponding upstream submodules.
Modified or wrapped behavior is documented in
`packages/easyeda-gateway/MIGRATION_SOURCES.md`.

## Bundled runtime dependencies

- JSZip 3.10.1 is dual-licensed under MIT or GPL-3.0-or-later. This project uses
  the MIT option. Copyright 2009-2016 Stuart Knightley, David Duponchel, Franz
  Buchinger, and António Afonso.
- `@tracespace/parser`, `@tracespace/plotter`, and `@tracespace/renderer`
  5.0.0-alpha.0 are MIT-licensed. Copyright 2015-present Michael Cousins and
  contributors.
- pypdf is an installed Python dependency under BSD-3-Clause and is not copied
  into the gateway wheel.

## Hardware-learning integration

- `integrations/jlc-hardware-learning-plugin/` preserves its existing MIT
  license and upstream history.
- Its generated runtime includes tldraw 5.1.1 under the tldraw license. The
  bundled license permits development use but prohibits production deployment
  without a qualifying tldraw trial, commercial, or alternative license. A
  verbatim copy is retained at
  `integrations/jlc-hardware-learning-plugin/THIRD_PARTY_LICENSES/tldraw-LICENSE.md`.
- `materials/sources/integrations/cowart` is MIT-licensed, Copyright 2026 Twox.

## No trademark grant

No license in this repository grants permission to use EasyEDA, 嘉立创EDA,
JLC, tldraw, or other third-party names or logos beyond nominative descriptions
allowed by applicable law.
