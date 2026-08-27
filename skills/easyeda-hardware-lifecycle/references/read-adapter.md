# Read-only EasyEDA adapter

## Scope

The first adapter captures only the currently active schematic page. It does not open or activate another page, run DRC, export files, read the PCB, modify primitives, or save the project.

The capture sequence is:

```text
discover local bridge
  -> require one explicit connected window
  -> capture project/document identity
  -> build and validate canonical READ plan
  -> re-check identity
  -> read active-page components and pins
  -> verify identity again inside the same EasyEDA execution
  -> normalize JSON
  -> atomically record snapshot, plan, envelope, and SHA-256 hashes
```

## Security and correctness boundaries

- Only loopback `http://127.0.0.1`, `localhost`, or `::1` bridge URLs are accepted.
- Health must report `service: easyeda-bridge`.
- With multiple connected EasyEDA windows, `--window-id` is mandatory.
- Every execution explicitly sends the chosen `windowId`.
- The typed plan is validated against the locked canonical API manifest before component capture.
- The generated code is a fixed template. User strings are JSON-encoded identity values; arbitrary JavaScript is not accepted.
- The template contains no create, modify, delete, save, open-document, or activate-document calls.
- Evidence directories are unique and never overwritten.

## Commands

From the Skill `scripts` directory:

```powershell
py easyeda_read.py discover
py easyeda_read.py identity --window-id <window-id>
py easyeda_read.py snapshot-active-schematic `
  --window-id <window-id> `
  --manifest <workbench>\materials\manifests\api-manifest.json `
  --evidence-dir <project>\evidence
```

If exactly one EasyEDA window is connected, `--window-id` can be omitted. Discovery never starts or stops a bridge process.

## Current normalized component fields

- primitive ID, component type, designator, value/name, unique ID;
- linked device, symbol, and footprint identities;
- schematic X/Y, rotation, and mirror state;
- BOM/PCB participation flags;
- Manufacturer, Manufacturer Part, Supplier, and Supplier Part;
- pin number, pin name, and explicit no-connect state.

Net topology, DRC, text-attribute geometry, and cross-page capture remain separate adapters. Visual export is implemented by the isolated [export adapters](export-adapter.md); on the installed profile all current-page PNG/PDF/SVG combinations are blocked before bridge execution, while qualified whole-schematic artifacts keep the same identity and evidence boundary.
