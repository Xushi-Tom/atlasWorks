AtlasWorks service layout

- control: control plane API. It accepts requests, manages task records, and enqueues migrated jobs.
- tiling: tiling workers split by service type. Use vector, raster, terrain, or tiles3d with ATLASWORKS_TILING_SERVICE.
- publisher: publication API and static publication serving.
- publish backends: optional containers managed by publisher. Nginx serves prebuilt static tile directories; TiTiler serves COG/GeoTIFF as dynamic raster tiles.
- common: cross-service configuration, database access, task state, artifact metadata, and utilities.

New code should live under the owning service folder. Put only deliberately shared modules in common.

TiTiler quick example

- Single COG TileJSON:
  `http://127.0.0.1:18002/cog/WebMercatorQuad/tilejson.json?url=%2Fapp%2FdataSource%2F111%2FK50E023014.tif`
- Single COG preview:
  `http://127.0.0.1:18002/cog/preview.png?url=%2Fapp%2FdataSource%2F111%2FK50E023014.tif`
- AtlasWorks dynamic publication now generates a MosaicJSON file for TiTiler, even for a single GeoTIFF.
- Multiple TIFFs are published through a MosaicJSON document and `/mosaicjson/...` endpoints, not by passing multiple files to `/cog`.
- Dynamic tiling works by reading only the requested z/x/y window from the source GeoTIFF or MosaicJSON-backed asset set and resampling it on demand.
