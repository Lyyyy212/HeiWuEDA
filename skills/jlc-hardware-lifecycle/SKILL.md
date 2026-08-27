---
name: jlc-hardware-lifecycle
description: JLC-prefixed alias for the complete EasyEDA hardware lifecycle, covering concept design, module design, schematic review, official exports and page navigation, BOM selection, guarded BOM writeback, and JLC Hardware Learning. Use when the user asks for the combined JLC/EasyEDA workflow rather than one isolated operation.
---

# JLC Hardware Lifecycle

This is the stable JLC-prefixed entrypoint for the existing
`easyeda-hardware-lifecycle` orchestrator. It is an alias, not a fork.

Before taking task actions, read and follow
[`../easyeda-hardware-lifecycle/SKILL.md`](../easyeda-hardware-lifecycle/SKILL.md)
completely. Treat that skill and its referenced stage, API, export, page,
learning, evidence, and artifact contracts as authoritative.

Do not copy lifecycle logic into this alias, construct raw `eda.*` calls, or
weaken the main skill's read-only defaults, evidence gates, BOM freeze rules,
or explicit save-authorization boundary. Route learning-canvas operations to
the installed `jlc-hardware-learning` plugin and `$jlc-hardware-learning` skill
exactly as the main skill requires.

If the sibling `easyeda-hardware-lifecycle` skill is unavailable, report the
missing dependency and stop before any live EasyEDA operation.
