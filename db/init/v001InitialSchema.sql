CREATE TABLE IF NOT EXISTS tf_build_jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'unknown',
    progress INTEGER NOT NULL DEFAULT 0,
    current_stage TEXT,
    message TEXT,
    output_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE tf_build_jobs IS '构建任务主表，记录所有地图切片、地形切片、转换等后台任务的生命周期状态。';
COMMENT ON COLUMN tf_build_jobs.id IS '任务唯一标识，对应应用层 taskId。';
COMMENT ON COLUMN tf_build_jobs.job_type IS '任务类型，如 indexed_tiles、terrain_tiles、tile_convert。';
COMMENT ON COLUMN tf_build_jobs.status IS '任务状态，如 queued、running、completed、failed、stopped、interrupted。';
COMMENT ON COLUMN tf_build_jobs.progress IS '任务进度，取值范围 0-100。';
COMMENT ON COLUMN tf_build_jobs.current_stage IS '任务当前阶段名称，用于前端和日志展示。';
COMMENT ON COLUMN tf_build_jobs.message IS '任务当前提示信息或最终结果摘要。';
COMMENT ON COLUMN tf_build_jobs.output_path IS '任务主要输出路径。';
COMMENT ON COLUMN tf_build_jobs.created_at IS '任务记录创建时间。';
COMMENT ON COLUMN tf_build_jobs.started_at IS '任务开始执行时间。';
COMMENT ON COLUMN tf_build_jobs.finished_at IS '任务完成、失败或停止时间。';
COMMENT ON COLUMN tf_build_jobs.updated_at IS '任务最近一次状态更新时间。';
COMMENT ON COLUMN tf_build_jobs.payload IS '完整任务快照，使用 JSONB 持久化当前内存态结构。';

CREATE INDEX IF NOT EXISTS idx_tf_build_jobs_status ON tf_build_jobs(status);
CREATE INDEX IF NOT EXISTS idx_tf_build_jobs_updated_at ON tf_build_jobs(updated_at DESC);

CREATE TABLE IF NOT EXISTS tf_job_events (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES tf_build_jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE tf_job_events IS '任务事件流水表，用于记录任务阶段变化、关键操作和审计信息。';
COMMENT ON COLUMN tf_job_events.id IS '事件主键，自增。';
COMMENT ON COLUMN tf_job_events.job_id IS '关联的任务 ID。';
COMMENT ON COLUMN tf_job_events.event_type IS '事件类型，如 created、stage_changed、failed、published。';
COMMENT ON COLUMN tf_job_events.event_at IS '事件发生时间。';
COMMENT ON COLUMN tf_job_events.details IS '事件详情 JSON 数据。';

CREATE INDEX IF NOT EXISTS idx_tf_job_events_job_id ON tf_job_events(job_id, event_at DESC);

CREATE TABLE IF NOT EXISTS tf_artifacts (
    id TEXT PRIMARY KEY,
    build_job_id TEXT REFERENCES tf_build_jobs(id) ON DELETE SET NULL,
    artifact_type TEXT NOT NULL,
    version TEXT,
    format TEXT,
    output_path TEXT NOT NULL,
    bounds JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tf_artifacts IS '构建产物表，描述一次任务生成的可管理输出物。';
COMMENT ON COLUMN tf_artifacts.id IS '产物唯一标识。';
COMMENT ON COLUMN tf_artifacts.build_job_id IS '产物来源任务 ID。';
COMMENT ON COLUMN tf_artifacts.artifact_type IS '产物类型，如 xyz_tiles、terrain、geojson、glb。';
COMMENT ON COLUMN tf_artifacts.version IS '产物版本号或版本标签。';
COMMENT ON COLUMN tf_artifacts.format IS '产物格式说明。';
COMMENT ON COLUMN tf_artifacts.output_path IS '产物输出目录或主文件路径。';
COMMENT ON COLUMN tf_artifacts.bounds IS '产物地理范围，JSON 结构。';
COMMENT ON COLUMN tf_artifacts.metadata IS '产物附加元数据，包含统计和 manifest 信息。';
COMMENT ON COLUMN tf_artifacts.created_at IS '产物创建时间。';

CREATE TABLE IF NOT EXISTS tf_publications (
    id TEXT PRIMARY KEY,
    artifact_id TEXT REFERENCES tf_artifacts(id) ON DELETE CASCADE,
    publish_type TEXT NOT NULL,
    publish_path TEXT NOT NULL,
    alias TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    browser_url TEXT,
    access_url TEXT,
    launch_url TEXT,
    sample_url TEXT,
    public_base_url TEXT,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tf_publications IS '发布记录表，记录产物发布到静态目录、服务目录或别名路径的情况。';
COMMENT ON COLUMN tf_publications.id IS '发布记录唯一标识。';
COMMENT ON COLUMN tf_publications.artifact_id IS '被发布的产物 ID。';
COMMENT ON COLUMN tf_publications.publish_type IS '发布类型，如 static、wmts、terrain_service。';
COMMENT ON COLUMN tf_publications.publish_path IS '发布后的实际路径。';
COMMENT ON COLUMN tf_publications.alias IS '对外别名或逻辑名称。';
COMMENT ON COLUMN tf_publications.status IS '发布状态，如 draft、published、archived。';
COMMENT ON COLUMN tf_publications.metadata IS '发布相关附加元数据。';
COMMENT ON COLUMN tf_publications.browser_url IS '发布目录浏览地址。';
COMMENT ON COLUMN tf_publications.access_url IS '发布服务访问地址（可含模板变量）。';
COMMENT ON COLUMN tf_publications.launch_url IS '用于前端快速打开的发布入口地址。';
COMMENT ON COLUMN tf_publications.sample_url IS '样例瓦片地址。';
COMMENT ON COLUMN tf_publications.public_base_url IS '发布地址拼接使用的基础域名或主机地址。';
COMMENT ON COLUMN tf_publications.published_at IS '正式发布时间。';
COMMENT ON COLUMN tf_publications.created_at IS '发布记录创建时间。';
COMMENT ON COLUMN tf_publications.updated_at IS '发布记录最近更新时间。';

CREATE TABLE IF NOT EXISTS tf_source_assets (
    id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tf_source_assets IS '源数据资产表，用于登记输入的栅格、DEM、矢量或三维模型资源。';
COMMENT ON COLUMN tf_source_assets.id IS '源数据资产唯一标识。';
COMMENT ON COLUMN tf_source_assets.asset_type IS '源数据类型，如 raster、dem、vector、model3d。';
COMMENT ON COLUMN tf_source_assets.name IS '源数据名称。';
COMMENT ON COLUMN tf_source_assets.path IS '源数据在存储中的路径。';
COMMENT ON COLUMN tf_source_assets.metadata IS '源数据元信息，如坐标系、范围、波段、校验和等。';
COMMENT ON COLUMN tf_source_assets.created_at IS '源数据登记时间。';
COMMENT ON COLUMN tf_source_assets.updated_at IS '源数据最近更新时间。';

CREATE TABLE IF NOT EXISTS tf_workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT REFERENCES tf_workspaces(id) ON DELETE SET NULL,
    workspace_type TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tf_workspaces IS '工作空间表，用于组织项目、分组和产物归属目录。';
COMMENT ON COLUMN tf_workspaces.id IS '工作空间唯一标识。';
COMMENT ON COLUMN tf_workspaces.name IS '工作空间名称。';
COMMENT ON COLUMN tf_workspaces.parent_id IS '父级工作空间 ID，用于形成树状结构。';
COMMENT ON COLUMN tf_workspaces.workspace_type IS '工作空间类型，如 group、workspace、folder。';
COMMENT ON COLUMN tf_workspaces.path IS '工作空间对应的逻辑路径或物理路径。';
COMMENT ON COLUMN tf_workspaces.metadata IS '工作空间附加元数据。';
COMMENT ON COLUMN tf_workspaces.created_at IS '工作空间创建时间。';
COMMENT ON COLUMN tf_workspaces.updated_at IS '工作空间最近更新时间。';
