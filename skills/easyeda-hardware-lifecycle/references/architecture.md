# Modular architecture

## Target shape

```text
LifecycleOrchestrator
  |-- ProjectKernel
  |     |-- ProjectStateService
  |     |-- ArtifactStore
  |     |-- GateEngine
  |     `-- ProvenanceAndDigest
  |-- StageModules
  |     |-- ConceptDesign
  |     |-- ModuleDesign
  |     |-- SchematicReview
  |     |-- BomSelection
  |     `-- BomWriteback
  |-- DomainServices
  |     |-- RequirementsAndTradeoffs
  |     |-- ElectricalConstraints
  |     |-- DesignRuleReview
  |     |-- PartQualification
  |     `-- ProcurementFieldMapping
  `-- InfrastructureAdapters
        |-- OfficialApiRegistry
        |-- EasyedaSessionGuard
        |-- EasyedaPageNavigator
        |-- EasyedaReadAdapter
        |-- EasyedaExportAdapter
        |-- NativePdfVisualAdapter (local-only official-PDF derivative)
        |-- EasyedaFormalExportAdapter
        |-- EasyedaDrcAdapter
        |-- EasyedaEvidenceBundleAdapter
        |-- OfflineSourceRenderAdapter (maintenance-only, policy disabled)
        |-- OfflineProjectSourceRenderAdapter (maintenance-only, policy disabled)
        |-- ExportSafetyController
        |-- GuardedWriteAdapter
        |-- DatasheetAndDistributorAdapters
        `-- OptionalLearningCanvasAdapter
```

## Dependency direction

Dependencies point downward only:

1. The orchestrator knows stage interfaces and gates, not EasyEDA method signatures.
2. Stage modules know domain services and artifact contracts, not HTTP, WebSocket, bridge ports, or raw JavaScript.
3. Domain services return decisions, findings, requirements, or typed operations. They do not save documents.
4. Infrastructure adapters own external formats and transport. The official API gateway is the only layer allowed to translate a typed operation into `eda.*` execution.
5. Project state records artifact references and digests, never large raw exports or distributor responses.

This boundary lets a future extension replace JLC Hardware Learning, a distributor, the bridge transport, or a design-review engine without rewriting the lifecycle.

`EasyedaPageNavigator` is a fixed infrastructure adapter rather than a stage
module. It owns same-schematic page enumeration, explicit activation, guarded
traversal, page-UUID verification, and original-tab restoration. Export and
domain adapters may consume its verified identity records, but they never embed
navigation JavaScript or infer that a visual artifact is page-scoped.

## Module contract

Every stage module implements the same conceptual interface:

```text
inspect(context) -> ReadSet
plan(ReadSet, priorArtifacts) -> StagePlan
execute(StagePlan) -> ArtifactEnvelope[]
validate(ArtifactEnvelope[]) -> GateResult
invalidate(changeEvent) -> InvalidationSet
```

`execute` means producing design artifacts for design stages. It does not imply a live EDA write. Live writes are restricted to the guarded write adapter.

Each module declares:

- module ID and contract version;
- required upstream artifact types;
- produced artifact types;
- acceptance rules and blocking unknowns;
- invalidation triggers;
- external adapters used;
- whether operations are read-only, ephemeral-write, or persistent-write.

## Project kernel

### ProjectStateService

Maintains the current lifecycle stage, stage status, gate evidence, upstream digests, blockers, and append-only history. It permits only one-stage advancement and explicit downstream invalidation.

### ArtifactStore

Stores files under the project, while state contains relative paths and SHA-256 digests. Large source exports remain separate immutable evidence files.

### GateEngine

Evaluates stage-specific acceptance criteria. It must distinguish `passed`, `blocked`, and `pending`; absence of an error is not a pass.

### ProvenanceAndDigest

Canonicalizes JSON before hashing, records the source, version, identity, timestamp, and acquisition method, and prevents plans from being reused after a page or upstream artifact changes.

## Stage modules

### ConceptDesign

Owns requirements, use cases, operating environment, system partitioning, power tree, critical interfaces, architecture alternatives, risks, target cost, verification strategy, and the chosen baseline.

### ModuleDesign

Owns one file per hardware module plus interface-control and electrical-constraint artifacts. A module can be revised independently, but interface changes invalidate all consumers.

### SchematicReview

Consumes immutable official exports or a frozen live snapshot. It produces severity-ranked findings, evidence links, an action plan, unresolved physical checks, and a release gate. It uses `hardware-design-review` for design judgment.

### BomSelection

Converts electrical and mechanical part requirements into candidate comparisons and final selections. It uses MPN as the universal identity, verifies datasheets and footprint/spec compatibility, dates stock and price evidence, and preserves DNP/variant/assembly notes.

The general `bom` skill can supply sourcing, distributor, datasheet, lifecycle, price, and alternate-selection logic. Do not import its KiCad-specific storage convention into this EasyEDA workflow: before writeback, the frozen `bom/final-bom.json` plus its digest is the selection authority; after writeback, the four verified EasyEDA procurement fields mirror that frozen decision.

### BomWriteback

Consumes only a frozen final BOM. It delegates to `jlc-bom-sync`, limits scope to the four procurement fields, and preserves the device, symbol, footprint, value, designator, unique ID, geometry, pins, and nets.

## Extension points

Add a new hardware domain by contributing a module profile matching `references/schemas/module-profile.schema.json` rather than changing the kernel. A profile may add requirements and checks for power, analog, RF, FPGA, high-speed digital, isolation, or EMC. It may not weaken lifecycle gates or bypass the official API gateway.

Add an EDA transport by implementing the session, read, export, and guarded-write adapter contracts. The stage modules remain unchanged.

## Export subsystem

Export orchestration is deliberately split by responsibility:

```text
Stage consumer
  -> ExportCapabilityMatrix
  -> ExportSafetyController
       -> qualified fixed adapter
            -> one official call in one bridge request
            -> identity and artifact validation
            -> immutable evidence

NativePdfVisualAdapter
  -> consumes one sealed official whole-schematic PDF execution
  -> performs zero EasyEDA calls
  -> emits bounded, digest-sealed PNG pages for JLC Hardware Learning

EasyedaEvidenceBundleAdapter
  -> invokes qualified adapters serially
  -> never batches their official calls
  -> local consistency audit

OfflineSourceRenderAdapter
  -> retained for parser regression only
  -> product-facing visual routes reject with DISABLED_BY_POLICY
```

The capability matrix is policy, not discovery: an API being declared does not make it executable. Native EasyEDA PNG/PDF are the only admitted schematic visuals; EPRO remains an archive format, not an image source. The safety controller owns the persistent single-flight lock and circuit breaker. Individual adapters own exact method signatures and artifact validation. The bundle owns only sequencing and cross-artifact checks. This keeps a future API change localized to one adapter and makes a slow or hanging operation attributable to one capability.
