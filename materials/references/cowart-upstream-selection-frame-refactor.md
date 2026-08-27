# Hardware Learning canvas migration note

The active `jlc-hardware-learning-plugin` uses a dedicated hardware-learning
canvas and keeps legacy Cowart compatibility only for reading older project
state and replaying the archived patch series.

## Public distribution boundary

- The active plugin is stored in `integrations/jlc-hardware-learning-plugin/`.
- The upstream Cowart revision remains a pinned Git submodule for MIT
  attribution and migration reproducibility.
- The numbered patches under `integrations/cowart-patches/` document the
  migration history; they are not applied automatically at runtime.
- Local acceptance exports, user paths, project paths, screenshots and live
  evidence are intentionally omitted from the public repository.
- Current behavior and safety constraints are defined by
  `materials/manifests/jlc-hardware-learning-profile.json` and the lifecycle
  references, not by historical acceptance notes.

The learning canvas cannot call EasyEDA directly. Official visual evidence must
enter through the guarded lifecycle adapter after project/document identity
checks. Image generation, analytics, automatic page switching and EasyEDA
writes remain disabled for learning mode.
