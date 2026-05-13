const API_BASE_URL = window.location.origin;

function normalizeRelativePath(path = '') {
    return String(path || '').trim().replace(/^\/+|\/+$/g, '').replace(/\\/g, '/');
}

function encodePathSegments(path = '') {
    const normalized = normalizeRelativePath(path);
    return normalized
        .split('/')
        .filter(Boolean)
        .map(segment => encodeURIComponent(segment))
        .join('/');
}

class AtlasWorksApi {
    constructor() {
        this.baseURL = API_BASE_URL;
    }

    normalizeJsonEnvelope(payload, status) {
        if (payload && typeof payload === 'object' && 'success' in payload && 'message' in payload && 'data' in payload) {
            return payload;
        }
        const success = status >= 200 && status < 400;
        return {
            success,
            code: success ? 'OK' : `HTTP_${status}`,
            message: success ? 'ok' : (payload?.error || payload?.message || `HTTP ${status}`),
            data: payload,
            meta: {}
        };
    }

    async request(url, options = {}) {
        const fullUrl = url.startsWith('http') ? url : `${this.baseURL}${url}`;
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            },
            ...options
        };

        const response = await fetch(fullUrl, defaultOptions);
        const contentType = response.headers.get('content-type') || '';
        const isJson = contentType.includes('application/json');

        if (isJson) {
            const payload = await response.json();
            const normalized = this.normalizeJsonEnvelope(payload, response.status);
            if (!response.ok) {
                const error = new Error(normalized?.message || `HTTP ${response.status}`);
                error.payload = normalized;
                error.status = response.status;
                error.code = normalized?.code;
                throw error;
            }
            return normalized;
        }

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || `HTTP ${response.status}`);
        }

        if (contentType.includes('text/')) {
            return await response.text();
        }

        return response;
    }

    async get(url, params = {}) {
        const target = new URL(url.startsWith('http') ? url : `${this.baseURL}${url}`);
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
                target.searchParams.append(key, value);
            }
        });
        return this.request(target.toString(), { method: 'GET' });
    }

    async post(url, data = {}) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async put(url, data = {}) {
        return this.request(url, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    async patch(url, data = {}) {
        return this.request(url, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    }

    async delete(url) {
        return this.request(url, { method: 'DELETE' });
    }

    async upload(url, formData) {
        return this.request(url, {
            method: 'POST',
            body: formData,
            headers: {}
        });
    }

    async getHealth() {
        return this.get('/api/health');
    }

    async getSystemInfo() {
        return this.get('/api/system/info');
    }

    async browseDatasources(path = '', options = {}) {
        const normalized = normalizeRelativePath(path);
        const endpoint = normalized ? `/api/datasources/${encodePathSegments(normalized)}` : '/api/datasources';
        const normalizedOptions = typeof options === 'string' ? { bounds: options } : (options || {});
        const params = {};
        if (normalizedOptions.bounds) params.bounds = normalizedOptions.bounds;
        if (normalizedOptions.page) params.page = normalizedOptions.page;
        if (normalizedOptions.pageSize) params.pageSize = normalizedOptions.pageSize;
        return this.get(endpoint, params);
    }

    async getDatasourceWorkspace() {
        return this.get('/api/datasources/workspace');
    }

    async getDatasourceInfo(filename, tileType = '') {
        return this.get(`/api/datasources/info/${encodePathSegments(filename)}`, { tileType });
    }

    getDatasourceFileUrl(filename) {
        return `${this.baseURL}/api/datasources/raw/${encodePathSegments(filename)}`;
    }

    async resolveDatasourceFiles(params) {
        return this.post('/api/datasources/resolve', params);
    }

    async uploadDataSourceFile(file, targetPath = '', overwrite = false, targetType = 'datasource') {
        const formData = new FormData();
        formData.append('file', file);
        if (targetPath) formData.append('targetPath', targetPath);
        formData.append('overwrite', overwrite ? '1' : '0');
        formData.append('targetType', targetType);
        return this.upload('/api/upload/file', formData);
    }

    async uploadZipArchive(file, targetPath = '', overwrite = false, stripTopLevel = true, targetType = 'datasource', extractFolderName = '') {
        const formData = new FormData();
        formData.append('file', file);
        if (targetPath) formData.append('targetPath', targetPath);
        formData.append('overwrite', overwrite ? '1' : '0');
        formData.append('stripTopLevel', stripTopLevel ? '1' : '0');
        formData.append('targetType', targetType);
        const folderName = String(extractFolderName || '').trim();
        if (folderName) formData.append('extractFolderName', folderName);
        return this.upload('/api/upload/zip', formData);
    }

    async uploadFolder(files, targetPath = '', overwrite = false, targetType = 'datasource') {
        const formData = new FormData();
        for (const file of files) {
            formData.append('files', file, file.name);
            formData.append('paths', file.webkitRelativePath || file.name);
        }
        if (targetPath) formData.append('targetPath', targetPath);
        formData.append('overwrite', overwrite ? '1' : '0');
        formData.append('targetType', targetType);
        return this.upload('/api/upload/folder', formData);
    }

    async browseResults(path = '', options = {}) {
        const normalizedOptions = options || {};
        return this.get('/api/results', {
            type: 'results',
            path: normalizeRelativePath(path),
            page: normalizedOptions.page,
            pageSize: normalizedOptions.pageSize
        });
    }

    async getWorkspaceFileInfo(path) {
        return this.get('/api/fileDetails', {
            type: 'results',
            path: normalizeRelativePath(path)
        });
    }

    getWorkspaceFileUrl(path) {
        return `${this.baseURL}/api/workspace/raw/${encodePathSegments(path)}`;
    }

    async getWorkspaceInfo() {
        return this.get('/api/workspace/info');
    }

    async createWorkspaceFolder(folderPath) {
        return this.post('/api/workspace/createFolder', { folderPath });
    }

    async createDatasourceFolder(folderPath) {
        return this.post('/api/datasources/createFolder', { folderPath });
    }

    async deleteDatasourceFolder(folderPath) {
        return this.delete(`/api/datasources/folder/${encodePathSegments(folderPath)}`);
    }

    async deleteDatasourceFile(filePath) {
        return this.delete(`/api/datasources/file/${encodePathSegments(filePath)}`);
    }

    async deleteWorkspaceFolder(folderPath) {
        return this.delete(`/api/workspace/folder/${encodePathSegments(folderPath)}`);
    }

    async deleteWorkspaceFile(filePath) {
        return this.delete(`/api/workspace/file/${encodePathSegments(filePath)}`);
    }

    async extractArchive(path, targetType = 'datasource', overwrite = false, extractFolderName = '') {
        const payload = {
            path: normalizeRelativePath(path),
            targetType,
            overwrite
        };
        const folderName = String(extractFolderName || '').trim();
        if (folderName) payload.extractFolderName = folderName;
        return this.post('/api/files/extract', payload);
    }

    async getAllTasks(params = {}) {
        return this.get('/api/tasks', params);
    }

    async getTaskStatus(taskId) {
        return this.get(`/api/tasks/${encodeURIComponent(taskId)}`);
    }

    async getTaskEvents(taskId) {
        return this.get(`/api/tasks/${encodeURIComponent(taskId)}/events`);
    }

    async stopTask(taskId) {
        return this.post(`/api/tasks/${encodeURIComponent(taskId)}/stop`);
    }

    async deleteTask(taskId) {
        return this.delete(`/api/tasks/${encodeURIComponent(taskId)}`);
    }

    async cleanupTasks(params = {}) {
        return this.post('/api/tasks/cleanup', params);
    }

    async createIndexedTiles(params) {
        return this.post('/api/tile/indexedTiles', params);
    }

    async geoserverPublish(params) {
        return this.post('/api/geoserver/publish', params);
    }

    async geoserverListLayers(params = {}) {
        return this.get('/api/geoserver/layers', params);
    }

    async geoserverGetLayer(name, params = {}) {
        return this.get(`/api/geoserver/layers/${encodeURIComponent(name)}`, params);
    }

    async geoserverDeleteLayer(name, params = {}) {
        const target = new URL(`${this.baseURL}/api/geoserver/layers/${encodeURIComponent(name)}`);
        Object.entries(params || {}).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
                target.searchParams.append(key, value);
            }
        });
        return this.request(target.toString(), { method: 'DELETE' });
    }

    async geoserverSeedLayer(name, params = {}) {
        const workspace = params.workspace;
        const payload = { ...params };
        delete payload.workspace;
        const target = new URL(`${this.baseURL}/api/geoserver/layers/${encodeURIComponent(name)}/seed`);
        if (workspace) target.searchParams.append('workspace', workspace);
        return this.request(target.toString(), {
            method: 'POST',
            body: JSON.stringify(payload),
            headers: { 'Content-Type': 'application/json' }
        });
    }

    async geoserverHealth() {
        return this.get('/api/geoserver/health');
    }

    async createTerrainTiles(params) {
        return this.post('/api/tile/terrain', params);
    }

    async create3DTiles(params) {
        return this.post('/api/tile/3dtiles', params);
    }

    async createVectorTiles(params) {
        return this.post('/api/tile/mvt', params);
    }

    async recommendConfig(params) {
        return this.post('/api/config/recommend', params);
    }

    async runPreflightCheck(params) {
        return this.post('/api/preflight', params);
    }

    async splitLargeFile(params) {
        return this.post('/api/datasources/split', params);
    }

    async scanNodataTiles(params) {
        return this.post('/api/tiles/nodata/scan', {
            tilesPath: normalizeRelativePath(params.path || params.tilesPath),
            transparencyThreshold: params.transparencyThreshold,
            includeDetails: params.includeDetails ?? true
        });
    }

    async deleteNodataTiles(params) {
        return this.post('/api/tiles/nodata/delete', {
            tilesPath: normalizeRelativePath(params.path || params.tilesPath),
            transparencyThreshold: params.transparencyThreshold,
            includeDetails: params.includeDetails ?? true
        });
    }

    async updateLayerJson(params) {
        const terrainPath = Array.isArray(params.terrainPath)
            ? params.terrainPath
            : normalizeRelativePath(params.folderPath || params.terrainPath).split('/').filter(Boolean);
        return this.post('/api/terrain/layer', {
            ...params,
            terrainPath
        });
    }

    async decompressTerrain(params) {
        const terrainPath = Array.isArray(params.terrainPath)
            ? params.terrainPath
            : normalizeRelativePath(params.folderPath || params.terrainPath).split('/').filter(Boolean);
        return this.post('/api/terrain/decompress', {
            ...params,
            terrainPath
        });
    }

    async convertTileFormat(params) {
        return this.post('/api/tile/convert', params);
    }

    async listArtifacts(params = {}) {
        return this.get('/api/artifacts', params);
    }

    async listPublications(params = {}) {
        return this.get('/api/publications', params);
    }

    async createPublication(params) {
        return this.post('/api/publications', params);
    }

    async getPublication(publicationId) {
        return this.get(`/api/publications/${encodeURIComponent(publicationId)}`);
    }

    async updatePublication(publicationId, params) {
        return this.put(`/api/publications/${encodeURIComponent(publicationId)}`, params);
    }

    async togglePublicationEnabled(publicationId, enabled) {
        return this.patch(`/api/publications/${encodeURIComponent(publicationId)}/enabled`, { enabled });
    }

    async deletePublication(publicationId) {
        return this.delete(`/api/publications/${encodeURIComponent(publicationId)}`);
    }

    async getRoutes(params = {}) {
        return this.get('/api/routes', params);
    }

    async updateContainer(params = {}) {
        return this.post('/api/container/update', params);
    }
}

export const api = new AtlasWorksApi();
