AtlasWorks service layout

- control: control plane API. It accepts requests, manages task records, and enqueues migrated jobs.
- tiling: tiling workers split by service type. Use vector, raster, terrain, or tiles3d with ATLASWORKS_TILING_SERVICE.
- publisher: publication API and static publication serving.
- publish backends: optional containers managed by publisher. Nginx serves prebuilt static tile directories; GeoServer serves datasource imagery as WMS/WMTS.
- common: cross-service configuration, database access, task state, artifact metadata, and utilities.

New code should live under the owning service folder. Put only deliberately shared modules in common.

Datasource imagery publication

- Datasource imagery is published through GeoServer.
- GeoServer publish returns WMS/WMTS access URLs and can submit GWC seed immediately after publish.
- Prebuilt tile directories continue to be served by Nginx under `/published/*`.
