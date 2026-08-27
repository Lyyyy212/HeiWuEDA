# License scope

## Lyyyy original work

Unless a file or directory carries a different license or is identified below
as third-party material, original source code and documentation in this
repository authored by Lyyyy are licensed under the
`PolyForm-Noncommercial-1.0.0` terms in [`LICENSE`](LICENSE).

The permitted scope is noncommercial use. Commercial use is not offered. This
includes, without limitation, incorporating the Lyyyy-authored work into a paid
product, paid service, commercial design workflow, resale, hosted commercial
service, or work performed for commercial advantage or monetary compensation.

Because commercial use is prohibited, this project is source-available and is
not OSI Open Source Software.

## Third-party exceptions

The root license does not relicense third-party material:

- `materials/sources/**` consists of pinned upstream Git submodules and remains
  under the license supplied by each upstream repository.
- `packages/easyeda-gateway/easyeda_gateway/official_runtime/*.min.js` contains
  source-pinned bundles derived from EasyEDA extension repositories and their
  bundled dependencies. Their original licenses remain in force.
- `integrations/jlc-hardware-learning-plugin/` currently preserves its existing
  MIT-licensed integration history. Its generated runtime also contains tldraw,
  whose separate license restricts production deployment without an applicable
  tldraw license.
- Files that contain their own copyright or license notice remain governed by
  that notice.

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for provenance and exact
source revisions. If a license boundary is unclear, do not redistribute the
affected file until it has been reviewed.
