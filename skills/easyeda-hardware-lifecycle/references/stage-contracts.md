# Stage contracts and gates

## Lifecycle state machine

```text
concept -> module_design -> schematic_review -> bom_selection -> bom_writeback
```

Iteration is expected. Forward movement is one stage at a time. An upstream change moves the project back to the earliest affected stage and marks every dependent stage pending.

## 1. Concept design

Inputs:

- product objective, use cases, users, environment, regulatory context;
- quantitative performance, interfaces, supply, size, cost, schedule, and production volume;
- existing boards, IP, preferred parts, manufacturing constraints, and explicit assumptions.

Outputs:

- `requirements.json` with stable requirement IDs and verification methods;
- `system-architecture.json` with blocks, interfaces, power tree, data/control flow, alternatives, tradeoffs, chosen baseline, risks, and unknowns;
- `verification-strategy.json` mapping requirements to analysis, simulation, inspection, or physical tests.

Gate `G1_CONCEPT_BASELINE` passes only when critical requirements are measurable, major interfaces and power domains are defined, architecture alternatives are compared, and blocking unknowns have owners or planned tests.

## 2. Module detailed design

Inputs:

- passed concept baseline and its digest;
- upstream requirements and system interfaces;
- relevant datasheets and domain constraints.

Outputs:

- `modules/<module-id>.json` for each subsystem;
- `interfaces.json` defining signal direction, levels, timing, connector/pin ownership, impedance or current constraints, and fault behavior;
- `electrical-constraints.json` for rails, clocks, resets, sequencing, analog budgets, protection, layout, thermal, and test points;
- calculations, simulation results, part requirements, and module verification plans.

Gate `G2_MODULE_DESIGN_READY` passes only when every module requirement is traced, inter-module interfaces agree on both ends, component requirements are implementation-ready, and critical calculations or simulations are attached.

Changing a connector, rail, voltage level, clock, data width, protocol, bandwidth, thermal assumption, or critical footprint invalidates all consuming modules and downstream stages.

## 3. Schematic review

Inputs:

- passed module-design digest;
- page-bound official schematic exports, netlist, BOM, DRC/ERC, and relevant datasheets;
- document identity and acquisition evidence.

Outputs:

- `schematic-snapshot.json` and immutable export hashes;
- `review-report.json` with P0-P3 findings, location, evidence, impact, recommendation, and confidence;
- `review-actions.json` separated into proposed, approved, applied, and verified states;
- `release-gate.json` with open physical, procurement, layout, and test evidence.

Gate `G3_SCHEMATIC_REVIEWED` passes only when no P0/P1 finding remains open, required P2 dispositions are recorded, document identity is stable across exports, and the review is based on the current module-design digest.

Do not treat a clean DRC as this gate passing. Do not apply actions unless the user explicitly requests writeback.

## 4. BOM selection

Inputs:

- reviewed schematic snapshot and design constraints;
- quantities, board variants, manufacturing path, target cost, lifecycle and supply-risk policy.

Outputs:

- `bom/requirements.json` keyed by reference/group and requirement IDs;
- `bom/candidates.json` with package/spec/datasheet/lifecycle/stock/price/alternate evidence;
- `bom/final-bom.json` with selection rationale, DNP/variant notes, and four EasyEDA procurement fields;
- `bom/final-bom.digest` produced from canonical final BOM content.

Gate `G4_BOM_FROZEN` passes only when each populated reference has a validated MPN and package/spec match, critical parts have lifecycle and alternate decisions, unmatched/ambiguous references are blocked, and the final BOM digest is recorded. Price and stock evidence must carry observation timestamps and be refreshed before ordering.

## 5. BOM writeback

Inputs:

- frozen final BOM and digest;
- current live EasyEDA page identity;
- fresh official PDF/BOM/netlist/DRC baseline;
- explicit scope limited to Manufacturer, Manufacturer Part, Supplier, and Supplier Part.

Outputs:

- page-local write plan and digest;
- acceptance-test report with temporary write/readback/restore evidence;
- fresh post-acceptance plan;
- apply journal, post-save readback, formal export comparison, and rollback result if needed.

Gate `G5_BOM_SYNC_VERIFIED` passes only after explicit save authorization, successful post-save readback, unchanged protected fields and connectivity, and recorded DRC/export differences. Empty BOM cells remain unspecified; they are never guessed or cleared implicitly.

## Invalidation matrix

| Change | Earliest invalidated stage |
|---|---|
| Product requirement, environment, cost model | `concept` |
| Architecture block, power tree, system interface | `concept` |
| Module circuit, timing, connector, level, footprint requirement | `module_design` |
| Schematic primitive, net, value, footprint, page identity | `schematic_review` |
| Selected MPN, supplier choice, DNP/variant rule | `bom_selection` |
| Only a failed or stale page-local write plan | `bom_writeback` |

Never silently repair state by advancing again. Record the invalidation reason and new upstream digest.
