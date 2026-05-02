AtlasWorks service layout

- control: control plane API. It accepts requests, manages task records, and enqueues migrated jobs.
- tiling: tiling workers split by service type. Use vector, raster, terrain, or tiles3d with ATLASWORKS_TILING_SERVICE.
- publisher: publication API and static publication serving.
- common: cross-service configuration, database access, task state, artifact metadata, and utilities.

New code should live under the owning service folder. Put only deliberately shared modules in common.
