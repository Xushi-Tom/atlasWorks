AtlasWorks service layout

- control: control plane API. It accepts requests, manages task records, and enqueues migrated jobs.
- tiling: tiling workers. Each container is selected by job type through ATLASWORKS_WORKER_JOB_TYPES.
- publisher: publication API and static publication serving.

The existing backend directory is the shared service kernel for now. It contains reusable route handlers,
task logic, database access, catalog logic, and utility modules used by the service entrypoints above.
Move code out of backend gradually when a module has a clear owner; do not add new container entrypoints
directly under backend.
