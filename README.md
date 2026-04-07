# atlasWorks

**AtlasWorks** is an open-source service platform for geospatial data building and publishing. It organises GeoTIFF, DEM, and other geospatial data assets into executable tasks, trackable artifacts, and externally accessible publication resources — providing a complete workflow from data preparation to result delivery.

## Features

| Area | Capability |
|------|-----------|
| **Tasks** | Create, update, delete, and execute processing tasks (process / convert / analyze / tile) against GeoTIFF or DEM inputs |
| **Artifacts** | Register and browse trackable data products with spatial metadata (CRS, bounding box, resolution, tags) |
| **Publish** | Expose artifacts as externally accessible resources (static, tiles, WMS, API) with active/inactive toggle |
| **Dashboard** | At-a-glance stats: task status breakdown, artifact count, active publications, recent activity |

## Tech stack

- **Backend**: Python 3.12 · [FastAPI](https://fastapi.tiangolo.com/) · [SQLAlchemy 2](https://docs.sqlalchemy.org/) · SQLite
- **Frontend**: Jinja2 templates · Bootstrap 5 · Vanilla JavaScript
- **Tests**: pytest · httpx (via `fastapi.testclient.TestClient`)

## Quick start

### 1 · Clone and install

```bash
git clone https://github.com/Xushi-Tom/atlasWorks.git
cd atlasWorks
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2 · Run the server

```bash
uvicorn app.main:app --reload
```

Open **http://localhost:8000** in your browser.

> The SQLite database (`atlasworks.db`) is created automatically on first run.

### 3 · Explore the API docs

Interactive Swagger UI: **http://localhost:8000/docs**

## Project layout

```
atlasWorks/
├── app/
│   ├── main.py           # FastAPI application, frontend routes, stats API
│   ├── database.py       # SQLAlchemy engine & session factory
│   ├── models.py         # ORM models: Task, Artifact, Publication
│   ├── schemas.py        # Pydantic v2 request/response schemas
│   └── routers/
│       ├── tasks.py      # /api/tasks  – CRUD + /run endpoint
│       ├── artifacts.py  # /api/artifacts – CRUD + filter by task
│       └── publish.py    # /api/publish  – CRUD + /toggle endpoint
├── static/
│   ├── css/style.css
│   └── js/app.js
├── templates/
│   ├── base.html         # Shared sidebar layout
│   ├── index.html        # Dashboard
│   ├── tasks.html        # Task management
│   ├── artifacts.html    # Artifact catalog
│   └── publish.html      # Publication manager
├── tests/
│   ├── conftest.py       # Shared fixtures (in-memory SQLite per test)
│   ├── test_tasks.py
│   ├── test_artifacts.py
│   └── test_publish.py
├── requirements.txt
└── README.md
```

## API overview

### Tasks — `/api/tasks`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all tasks |
| `POST` | `/` | Create a task |
| `GET` | `/{id}` | Get a task |
| `PUT` | `/{id}` | Update a task |
| `DELETE` | `/{id}` | Delete a task (cascades to artifacts) |
| `POST` | `/{id}/run` | Execute a task asynchronously |

### Artifacts — `/api/artifacts`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all artifacts |
| `POST` | `/` | Register an artifact |
| `GET` | `/{id}` | Get an artifact |
| `PUT` | `/{id}` | Update artifact metadata |
| `DELETE` | `/{id}` | Delete an artifact (cascades to publications) |
| `GET` | `/task/{task_id}` | List artifacts belonging to a task |

### Publish — `/api/publish`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List all publications |
| `POST` | `/` | Create a publication |
| `GET` | `/{id}` | Get a publication |
| `PUT` | `/{id}` | Update a publication |
| `DELETE` | `/{id}` | Delete a publication |
| `POST` | `/{id}/toggle` | Toggle active ↔ inactive |

## Running tests

```bash
python -m pytest tests/ -v
```

All tests use an isolated in-memory SQLite database — no external services required.

## Supported data types

| Type | Description |
|------|-------------|
| `GeoTIFF` | Georeferenced raster imagery |
| `DEM` | Digital Elevation Model |
| `Other` | Any other geospatial asset |

## Task types

| Type | Description |
|------|-------------|
| `process` | General-purpose processing (output: GeoTIFF) |
| `convert` | Format conversion (output: PNG) |
| `analyze` | Spatial analysis (output: GeoJSON) |
| `tile` | Tile generation for map viewers |

## License

MIT
