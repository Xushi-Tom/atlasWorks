// 全局变量
let currentDatasourcePath = '';
let filePickerCallback = null;
let taskPollingIntervals = new Map();
let autoRefreshInterval = null;
let autoRefreshEnabled = false;
// 全局变量：当前工作空间路径
let currentWorkspacePath = '';
let mapBandDetectionTimer = null;
let currentDatasourceTab = 'library';
let currentToolsSubsection = 'toolNodataTiles';
let currentSystemSubsection = 'systemUpdatesCard';

const TOOL_VIEW_META = {
    toolNodataTiles: { title: '透明瓦片处理', subtitle: '扫描并清理工作空间中的透明瓦片。' },
    toolLayerJson: { title: 'layer.json 生成与修复', subtitle: '为地形成果补齐或修复 layer.json，并按需重算 bounds。' },
    toolTerrainDecompress: { title: 'Terrain 解压', subtitle: '把 .terrain.gz 输出恢复为 .terrain 文件。' },
    toolPreflight: { title: '构建预检查', subtitle: '在正式切片前检查输入、范围和参数风险。' },
    toolArtifacts: { title: '构建产物', subtitle: '查看已产出的构建结果与可发布资产。' },
    toolPublications: { title: '发布台账', subtitle: '查看和刷新发布记录，追踪产物发布情况。' },
    toolTileConverter: { title: '瓦片格式转换', subtitle: '在 flat 与 nested 瓦片目录结构之间转换。' },
    toolSplit: { title: '大文件拆分', subtitle: '将超大 TIFF 按分块规则拆成更易处理的小文件。' }
};

const SYSTEM_VIEW_META = {
    systemUpdatesCard: { title: '系统更新', subtitle: '检查当前版本、系统状态和更新动作摘要。' },
    systemRoutesCard: { title: 'API 路由', subtitle: '查看服务暴露的接口列表和分类说明。' },
    systemConfigCard: { title: '系统配置', subtitle: '查看服务端口、数据目录与后端服务配置。' }
};

function renderIcon(name, className = '') {
    const icons = {
        folder: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3.5 8.5A2.5 2.5 0 0 1 6 6h4l2 2h6A2.5 2.5 0 0 1 20.5 10.5v7A2.5 2.5 0 0 1 18 20H6a2.5 2.5 0 0 1-2.5-2.5z"/>
            </svg>
        `,
        folderOpen: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3.5 8.5A2.5 2.5 0 0 1 6 6h4l2 2h6A2.5 2.5 0 0 1 20.5 10.5v1.2"/>
                <path d="M4.5 11.5h15l-1.8 6A2 2 0 0 1 15.8 19H6.2a2 2 0 0 1-1.9-1.5z"/>
            </svg>
        `,
        file: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M7 3.5h6l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 6 20V5A1.5 1.5 0 0 1 7.5 3.5z"/>
                <path d="M13 3.5V8h4.5"/>
            </svg>
        `,
        back: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10 7l-5 5 5 5"/>
                <path d="M19 12H5"/>
            </svg>
        `,
        trash: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 7h16"/>
                <path d="M9 7V4.5h6V7"/>
                <path d="M7.5 7l1 12.5h7L16.5 7"/>
                <path d="M10 11.5v4.5"/>
                <path d="M14 11.5v4.5"/>
            </svg>
        `,
        view: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/>
                <circle cx="12" cy="12" r="2.7"/>
            </svg>
        `,
        stop: `
            <svg viewBox="0 0 24 24" fill="currentColor">
                <rect x="6.5" y="6.5" width="11" height="11" rx="2"/>
            </svg>
        `,
        success: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="8"/>
                <path d="M8.5 12.4l2.2 2.2 4.8-5"/>
            </svg>
        `,
        error: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="8"/>
                <path d="M9.5 9.5l5 5m0-5l-5 5"/>
            </svg>
        `,
        warning: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 4.5l8 14a1 1 0 0 1-.87 1.5H4.87A1 1 0 0 1 4 18.5z"/>
                <path d="M12 9v4.5"/>
                <path d="M12 17h.01"/>
            </svg>
        `,
        info: `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="8"/>
                <path d="M12 10.5V16"/>
                <path d="M12 8h.01"/>
            </svg>
        `
    };

    const finalClassName = ['inline-icon', className].filter(Boolean).join(' ');
    return `<span class="${finalClassName}" aria-hidden="true">${icons[name] || icons.info}</span>`;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function parseCommaList(value) {
    return String(value || '')
        .split(',')
        .map(item => item.trim())
        .filter(Boolean);
}

let atlasWorksAppInitialized = false;

function bindModalBackdropClose() {
    const modal = document.getElementById('modal');
    if (!modal || modal.dataset.backdropBound === '1') {
        return;
    }

    modal.addEventListener('click', function(e) {
        if (e.target === this) {
            closeModal();
        }
    });
    modal.dataset.backdropBound = '1';
}

function bootAtlasWorksApp() {
    if (atlasWorksAppInitialized) {
        return;
    }
    atlasWorksAppInitialized = true;
    initializeApp();
}

// 页面初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootAtlasWorksApp);
} else {
    queueMicrotask(bootAtlasWorksApp);
}

// 应用初始化
async function initializeApp() {
    try {
        bindModalBackdropClose();
        initializeEvents();
        initializeUploadInputs();
        switchDatasourceTab(currentDatasourceTab);
        switchToolsSubsection(currentToolsSubsection, { syncSidebar: false, reveal: false });
        switchSystemSubsection(currentSystemSubsection, { syncSidebar: false, reveal: false });
        updateBodySectionState('dashboard');
        await loadDashboard();
        await updateSystemInfo(); // 初始化系统信息
        startPeriodicTasks();
        startDateTimeUpdate();
        console.log('AtlasWorks管理系统初始化完成');
    } catch (error) {
        console.error('应用初始化失败:', error);
        showMessage('系统初始化失败，请刷新页面重试', 'error');
    }
}

// 全局错误处理
window.addEventListener('error', function(event) {
    console.error('全局错误:', event.error);
    console.error('错误位置:', event.filename, '行号:', event.lineno);
});

window.addEventListener('unhandledrejection', function(event) {
    console.error('未处理的Promise拒绝:', event.reason);
    console.error('Promise:', event.promise);
});

// 检查系统状态
async function checkSystemStatus() {
    try {
        const health = await terraForgeAPI.getHealth();
        const statusElement = document.getElementById('systemStatus');
        if (statusElement) {
            const indicator = statusElement.querySelector('.status-indicator');
            if (health.status === 'healthy') {
                indicator.style.color = '#4CAF50';
                statusElement.querySelector('span').textContent = '系统正常';
            } else {
                indicator.style.color = '#f44336';
                statusElement.querySelector('span').textContent = '系统异常';
            }
        }
    } catch (error) {
        console.error('系统状态检查失败:', error);
    }
}

// 初始化事件监听
function initializeEvents() {
    // 菜单切换事件
    document.querySelectorAll('.nav-item:not(.nav-group)').forEach(item => {
        item.addEventListener('click', function(event) {
            switchSection(this.dataset.section);
        });
    });

    document.querySelectorAll('.nav-group-link').forEach(item => {
        item.addEventListener('click', function(event) {
            event.stopPropagation();
            const groupItem = this.closest('.nav-group');
            const section = this.dataset.section;
            const firstSubitem = groupItem?.querySelector('.nav-subitem');
            const isExpanded = groupItem?.classList.contains('expanded');
            const isActive = groupItem?.classList.contains('active');

            if (isActive) {
                setNavGroupExpanded(section, !isExpanded);
                return;
            }

            setNavGroupExpanded(section, true);
            switchSection(section, {
                subsectionId: this.dataset.subsection || firstSubitem?.dataset.subsection,
                expandGroup: true
            });
        });
    });

    document.querySelectorAll('.nav-toggle').forEach(item => {
        item.addEventListener('click', function(event) {
            event.stopPropagation();
            toggleNavGroup(this.dataset.section);
        });
    });

    document.querySelectorAll('.nav-subitem').forEach(item => {
        item.addEventListener('click', function(event) {
            event.stopPropagation();
            switchSection(this.dataset.section, {
                subsectionId: this.dataset.subsection
            });
        });
    });

    // 表单提交事件
    initializeFormEvents();
}

function initializeUploadInputs() {
    const singleInput = document.getElementById('singleUploadInput');
    const folderInput = document.getElementById('folderUploadInput');

    if (singleInput) {
        singleInput.addEventListener('change', async () => {
            const file = singleInput.files && singleInput.files[0];
            if (!file) return;
            await handleSingleUpload(file);
            singleInput.value = '';
        });
    }

    if (folderInput) {
        folderInput.addEventListener('change', async () => {
            const files = Array.from(folderInput.files || []);
            if (!files.length) return;
            await handleFolderUpload(files);
            folderInput.value = '';
        });
    }
}

function syncSidebarNavigation(sectionName, subsectionId) {
    document.querySelectorAll('.nav-item').forEach(item => {
        const isActive = item.dataset.section === sectionName;
        item.classList.toggle('active', isActive);
    });

    document.querySelectorAll('.nav-subitem').forEach(item => {
        item.classList.toggle('active', item.dataset.section === sectionName && item.dataset.subsection === subsectionId);
    });
}

function setNavGroupExpanded(sectionName, expanded) {
    const group = document.querySelector(`.nav-group[data-section="${sectionName}"]`);
    if (!group) {
        return;
    }
    group.classList.toggle('expanded', expanded);
    const toggle = group.querySelector('.nav-toggle');
    if (toggle) {
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }
}

function toggleNavGroup(sectionName) {
    const group = document.querySelector(`.nav-group[data-section="${sectionName}"]`);
    if (!group) {
        return;
    }
    setNavGroupExpanded(sectionName, !group.classList.contains('expanded'));
}

function revealSectionBlock(elementId) {
    if (!elementId) {
        return;
    }
    const el = document.getElementById(elementId);
    if (!el) {
        return;
    }
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.add('tool-block-highlight');
    window.setTimeout(() => el.classList.remove('tool-block-highlight'), 1200);
}

// 切换页面section
function switchSection(sectionName, options = {}) {
    syncSidebarNavigation(sectionName, options.subsectionId);

    // 切换内容区域
    document.querySelectorAll('.content-section').forEach(section => {
        section.classList.remove('active');
    });
    document.getElementById(sectionName).classList.add('active');
    updateBodySectionState(sectionName);

    if (sectionName === 'tools') {
        if (options.expandGroup !== false) {
            setNavGroupExpanded('tools', true);
        }
        switchToolsSubsection(options.subsectionId || currentToolsSubsection, {
            syncSidebar: true,
            reveal: options.reveal === true
        });
    } else if (sectionName === 'system') {
        if (options.expandGroup !== false) {
            setNavGroupExpanded('system', true);
        }
        switchSystemSubsection(options.subsectionId || currentSystemSubsection, {
            syncSidebar: true,
            reveal: options.reveal === true
        });
    }

    // 加载对应数据
    loadSectionData(sectionName);
}

function updateBodySectionState(sectionName) {
    document.body.classList.toggle('dashboard-active', sectionName === 'dashboard');
}

// 加载section数据
async function loadSectionData(sectionName) {
    switch (sectionName) {
        case 'dashboard':
            await loadDashboard();
            break;
        case 'datasource':
            await loadDatasources();
            await loadDatasourceWorkspaceInfo();
            break;
        case 'workspace':
            await loadWorkspace();
            break;
        case 'tasks':
            await loadTasks();
            await refreshTaskReleasePanel();
            break;
        case 'tools':
            await loadToolsData();
            break;
        case 'system':
            await loadSystemManagement();
            break;
    }
}

// 加载仪表盘数据
async function loadDashboard() {
    try {
        const tasks = await terraForgeAPI.getAllTasks();
        updateTaskOverviewCard(tasks);
    } catch (error) {
        console.error('仪表盘数据加载失败:', error);
    }
}


// 更新任务概览卡片
function updateTaskOverviewCard(data) {
    const container = document.getElementById('taskOverview');
    if (!data) {
        container.innerHTML = '<div class="message error">任务信息加载失败</div>';
        return;
    }
    
    const tasks = data.tasks || {};
    const taskList = Object.values(tasks);
    const completedTasks = taskList.filter(task => task.status === 'completed').length;
    const runningTasks = taskList.filter(task => task.status === 'running').length;
    const failedTasks = taskList.filter(task => task.status === 'failed').length;
    
    container.innerHTML = `
        <div class="task-stats">
            <div class="stat-item">
                <div class="stat-number">${taskList.length}</div>
                <div class="stat-label">总任务数</div>
            </div>
            <div class="stat-item">
                <div class="stat-number" style="color: #28a745">${completedTasks}</div>
                <div class="stat-label">已完成</div>
            </div>
            <div class="stat-item">
                <div class="stat-number" style="color: #ffc107">${runningTasks}</div>
                <div class="stat-label">运行中</div>
            </div>
            <div class="stat-item">
                <div class="stat-number" style="color: #dc3545">${failedTasks}</div>
                <div class="stat-label">失败</div>
            </div>
        </div>
    `;
}

// 加载数据源列表
async function loadDatasources(path = '') {
    try {
        showLoading('datasourceList');
        const data = await terraForgeAPI.browseDatasources(path);
        console.log('数据源API返回数据:', data);
        updateDatasourceList(data);
        updateDatasourceBreadcrumb(path);
        currentDatasourcePath = path;
    } catch (error) {
        console.error('数据源加载失败:', error);
        showError('datasourceList', '数据源加载失败');
    }
}

function switchDatasourceTab(tabName) {
    currentDatasourceTab = tabName || 'library';
    document.querySelectorAll('[data-tab-group="datasource"]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === currentDatasourceTab);
    });
    document.querySelectorAll('.datasource-tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.dataset.datasourceTab === currentDatasourceTab);
    });

    if (currentDatasourceTab === 'import') {
        loadDatasourceWorkspaceInfo();
    }
}

function switchToolsSubsection(subsectionId, options = {}) {
    currentToolsSubsection = subsectionId || 'toolNodataTiles';
    document.querySelectorAll('#tools .tool-block').forEach(block => {
        const isActive = block.id === currentToolsSubsection;
        block.classList.toggle('active', isActive);
        block.style.display = isActive ? '' : 'none';
    });

    const meta = TOOL_VIEW_META[currentToolsSubsection] || TOOL_VIEW_META.toolNodataTiles;
    const titleEl = document.getElementById('toolsSectionTitle');
    const subtitleEl = document.getElementById('toolsSectionSubtitle');
    if (titleEl) titleEl.textContent = meta.title;
    if (subtitleEl) subtitleEl.textContent = meta.subtitle;

    if (options.syncSidebar !== false) {
        syncSidebarNavigation('tools', currentToolsSubsection);
    }
    if (options.reveal !== false) {
        window.requestAnimationFrame(() => revealSectionBlock(currentToolsSubsection));
    }
}

function switchSystemSubsection(subsectionId, options = {}) {
    currentSystemSubsection = subsectionId || 'systemUpdatesCard';
    document.querySelectorAll('#system .system-block').forEach(block => {
        const isActive = block.id === currentSystemSubsection;
        block.classList.toggle('active', isActive);
        block.style.display = isActive ? '' : 'none';
    });

    const meta = SYSTEM_VIEW_META[currentSystemSubsection] || SYSTEM_VIEW_META.systemUpdatesCard;
    const titleEl = document.getElementById('systemSectionTitle');
    const subtitleEl = document.getElementById('systemSectionSubtitle');
    if (titleEl) titleEl.textContent = meta.title;
    if (subtitleEl) subtitleEl.textContent = meta.subtitle;

    if (options.syncSidebar !== false) {
        syncSidebarNavigation('system', currentSystemSubsection);
    }
    if (options.reveal !== false) {
        window.requestAnimationFrame(() => revealSectionBlock(currentSystemSubsection));
    }
}

function switchToolsTab(tabName) {
    const firstMatching = document.querySelector(`.nav-subitem[data-section="tools"][data-tools-tab="${tabName}"]`);
    switchToolsSubsection(firstMatching?.dataset.subsection || currentToolsSubsection, { reveal: false });
}

function switchSystemTab(tabName) {
    const firstMatching = document.querySelector(`.nav-subitem[data-section="system"][data-system-tab="${tabName}"]`);
    switchSystemSubsection(firstMatching?.dataset.subsection || currentSystemSubsection, { reveal: false });
}

async function loadDatasourceWorkspaceInfo() {
    const container = document.getElementById('datasourceWorkspaceInfo');
    if (!container) return;
    container.innerHTML = '<div class="loading">加载中...</div>';
    try {
        const result = await terraForgeAPI.getDatasourceWorkspace();
        const ws = result?.workspace || {};
        const hostHint = ws.hostPathHint || '';
        container.innerHTML = `
            <div class="info-row"><span class="info-label">容器目录</span><span class="info-value">${escapeHtml(ws.containerPath || '')}</span></div>
            <div class="info-row"><span class="info-label">宿主机挂载</span><span class="info-value">${escapeHtml(hostHint || '未配置')}</span></div>
            <div class="info-row"><span class="info-label">提示</span><span class="info-value">docker-compose 默认: atlasWorks/runtime/dataSource</span></div>
        `;
    } catch (e) {
        container.innerHTML = `<div class="message error">加载失败: ${escapeHtml(e.message)}</div>`;
    }
}

// 更新数据源列表
function updateDatasourceList(data) {
    const container = document.getElementById('datasourceList');
    if (!data || (!data.directories && !data.datasources)) {
        container.innerHTML = '<div class="message info">没有找到数据源</div>';
        return;
    }
    
    let html = '';
    
    // 添加目录
    if (data.directories) {
        data.directories.forEach(dir => {
            html += `
                <div class="file-item" onclick="navigateDatasource('${dir.path}')">
                    ${renderIcon('folder', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name">${dir.name}</div>
                        <div class="file-details">目录</div>
                    </div>
                </div>
            `;
        });
    }
    
    // 添加文件
    if (data.datasources) {
        data.datasources.forEach(file => {
            html += `
                <div class="file-item" onclick="showFileDetails('${file.path}', '${file.name}')">
                    ${renderIcon('file', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name">${file.name}</div>
                        <div class="file-details">${file.sizeFormatted || file.size || file.format}</div>
                    </div>
                </div>
            `;
        });
    }
    
    container.innerHTML = html;
}

// 更新数据源导航
function updateDatasourceBreadcrumb(path) {
    const container = document.getElementById('datasourceBreadcrumb');
    if (!path) {
        container.innerHTML = '<span class="breadcrumb-item active">根目录</span>';
        return;
    }
    
    const parts = path.split('/').filter(p => p);
    let html = '<span class="breadcrumb-item" onclick="loadDatasources(\'\')">根目录</span>';
    
    let currentPath = '';
    parts.forEach((part, index) => {
        currentPath += part;
        if (index === parts.length - 1) {
            html += ` / <span class="breadcrumb-item active">${part}</span>`;
        } else {
            html += ` / <span class="breadcrumb-item" onclick="loadDatasources('${currentPath}')">${part}</span>`;
        }
        currentPath += '/';
    });
    
    container.innerHTML = html;
}

// 导航到数据源目录
function navigateDatasource(path) {
    loadDatasources(path);
}

// 选择数据源文件
function selectDatasource(path) {
    if (filePickerCallback) {
        filePickerCallback(path);
        closeModal();
    } else {
        showMessage(`已选择文件: ${path}`, 'success');
    }
}

function triggerUploadSingleFile() {
    const input = document.getElementById('singleUploadInput');
    if (!input) return;
    input.accept = '.tif,.tiff,.zip,.txt,.png,.jpg,.jpeg';
    input.click();
}

function triggerUploadFolder() {
    const input = document.getElementById('folderUploadInput');
    if (!input) return;
    input.click();
}

async function handleSingleUpload(file) {
    const panel = document.getElementById('uploadResult');
    if (panel) panel.innerHTML = '<div class="loading">上传中...</div>';

    try {
        const targetPath = document.getElementById('uploadTargetPath')?.value?.trim() || '';
        const overwrite = !!document.getElementById('uploadOverwrite')?.checked;
        const stripZipRoot = !!document.getElementById('uploadStripZipRoot')?.checked;

        let result;
        if (String(file.name || '').toLowerCase().endsWith('.zip')) {
            result = await terraForgeAPI.uploadZipArchive(file, targetPath, overwrite, stripZipRoot);
        } else {
            result = await terraForgeAPI.uploadDataSourceFile(file, targetPath, overwrite);
        }

        const files = (result.files || []).slice(0, 10).map(p => `
            <div class="info-row"><span class="info-label">${escapeHtml(p)}</span><span class="info-value">ok</span></div>
        `).join('');

        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">结果</span><span class="info-value">${escapeHtml(result.message || '完成')}</span></div>
                    <div class="info-row"><span class="info-label">数量</span><span class="info-value">${result.count ?? 1}</span></div>
                </div>
                ${files ? `<div class="info-list">${files}</div>` : ''}
            `;
        }

        showMessage('导入成功', 'success');
        switchDatasourceTab('library');
        await loadDatasources(currentDatasourcePath || '');
    } catch (e) {
        if (panel) panel.innerHTML = `<div class="message error">上传失败: ${escapeHtml(e.message)}</div>`;
        showMessage(`上传失败: ${e.message}`, 'error');
    }
}

async function handleFolderUpload(files) {
    const panel = document.getElementById('uploadResult');
    if (panel) panel.innerHTML = '<div class="loading">上传文件夹中...</div>';

    try {
        const targetPath = document.getElementById('uploadTargetPath')?.value?.trim() || '';
        const overwrite = !!document.getElementById('uploadOverwrite')?.checked;
        const result = await terraForgeAPI.uploadFolder(files, targetPath, overwrite);

        const sample = (result.files || []).slice(0, 10).map(p => `
            <div class="info-row"><span class="info-label">${escapeHtml(p)}</span><span class="info-value">ok</span></div>
        `).join('');

        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">结果</span><span class="info-value">${escapeHtml(result.message || '完成')}</span></div>
                    <div class="info-row"><span class="info-label">数量</span><span class="info-value">${result.count ?? 0}</span></div>
                </div>
                ${sample ? `<div class="info-list">${sample}</div>` : ''}
            `;
        }

        showMessage('文件夹导入完成', 'success');
        switchDatasourceTab('library');
        await loadDatasources(currentDatasourcePath || '');
    } catch (e) {
        if (panel) panel.innerHTML = `<div class="message error">上传失败: ${escapeHtml(e.message)}</div>`;
        showMessage(`上传失败: ${e.message}`, 'error');
    }
}

// 加载工作空间
async function loadWorkspace() {
    try {
        showLoading('workspaceList');
        await loadWorkspaceFiles();
    } catch (error) {
        console.error('工作空间加载失败:', error);
        showError('workspaceList', '工作空间加载失败');
    }
}

// 进入/刷新目录时，唯一入口
async function loadWorkspaceFiles(path) {
    if (typeof path === 'string') {
        currentWorkspacePath = path;
    }
    console.log('当前 currentWorkspacePath:', currentWorkspacePath);
    try {
        const data = await terraForgeAPI.browseResults(currentWorkspacePath);
        updateWorkspaceFileList(data, currentWorkspacePath);
        updateWorkspaceBreadcrumb(currentWorkspacePath); // 每次刷新都更新面包屑导航
    } catch (error) {
        showError('workspaceList', '加载工作空间文件列表失败');
    }
}

// 更新工作空间导航
function updateWorkspaceBreadcrumb(path) {
    console.log('更新工作空间导航, 路径:', path);
    const container = document.getElementById('workspaceBreadcrumb');
    if (!path) {
        container.innerHTML = '<span class="breadcrumb-item active">根目录</span>';
        return;
    }
    
    const parts = path.split('/').filter(p => p);
    let html = '<span class="breadcrumb-item" onclick="loadWorkspaceFiles(\'\')">根目录</span>';
    
    let currentPath = '';
    parts.forEach((part, index) => {
        currentPath += part;
        if (index === parts.length - 1) {
            html += ` / <span class="breadcrumb-item active">${part}</span>`;
        } else {
            html += ` / <span class="breadcrumb-item" onclick="loadWorkspaceFiles('${currentPath}')">${part}</span>`;
        }
        currentPath += '/';
    });
    
    container.innerHTML = html;
}

// 渲染文件列表，目录点击事件必须是 loadWorkspaceFiles('${fullPath}')
function updateWorkspaceFileList(data, currentPath) {
    const container = document.getElementById('workspaceList');
    if (!data || (!data.directories && !data.files)) {
        container.innerHTML = '<div class="message info">目录为空</div>';
        return;
    }
    let html = '';
    // 添加目录
    if (data.directories) {
        data.directories.forEach(dir => {
            const fullPath = currentPath ? `${currentPath}/${dir.name}` : dir.name;
            html += `
                <div class="file-item" onclick="loadWorkspaceFiles('${fullPath}')">
                    ${renderIcon('folder', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name">${dir.name}</div>
                        <div class="file-details">目录</div>
                    </div>
                    <div class="file-actions">
                        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); renameWorkspaceItem('${fullPath}', 'folder')">
                            重命名
                        </button>
                        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); moveWorkspaceItemPrompt('${fullPath}')">
                            移动
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteWorkspaceItem('${fullPath}', 'folder')">
                            ${renderIcon('trash', 'btn-icon')}删除
                        </button>
                    </div>
                </div>
            `;
        });
    }
    // 添加文件
    if (data.files) {
        data.files.forEach(file => {
            const fullPath = currentPath ? `${currentPath}/${file.name}` : file.name;
            const modifiedTime = file.modifiedTime ? new Date(file.modifiedTime * 1000).toLocaleString() : '-';
            html += `
                <div class="file-item" onclick="showFileDetails('${fullPath}', '${file.name}', 'results')">
                    ${renderIcon('file', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name">${file.name}</div>
                        <div class="file-details">${file.sizeFormatted || file.size || '-'} | ${modifiedTime}</div>
                    </div>
                    <div class="file-actions">
                        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); renameWorkspaceItem('${fullPath}', 'file')">
                            重命名
                        </button>
                        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); moveWorkspaceItemPrompt('${fullPath}')">
                            移动
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteWorkspaceItem('${fullPath}', 'file')">
                            ${renderIcon('trash', 'btn-icon')}删除
                        </button>
                    </div>
                </div>
            `;
        });
    }
    container.innerHTML = `<div class="file-browser"><div class="file-list">${html}</div></div>`;
}

// 加载任务列表
async function loadTasks() {
    try {
        showLoading('taskList');
        const data = await terraForgeAPI.getAllTasks();
        updateTaskList(data);
        await refreshTaskReleasePanel(data);
    } catch (error) {
        console.error('任务列表加载失败:', error);
        showError('taskList', '任务列表加载失败');
    }
}

function renderTaskReleaseActions(artifacts, publications, taskData) {
    const tasks = Object.values(taskData?.tasks || {});
    const publishableTasks = tasks.filter(task => task?.status === 'completed' && task?.result?.artifactId);
    const publishedArtifactIds = new Set((publications || []).map(item => item.artifactId).filter(Boolean));

    const taskCards = publishableTasks.slice(0, 8).map(task => `
        <div class="info-item">
            <label>${escapeHtml(task.taskId)}</label>
            <span>${escapeHtml(task.result.artifactId || '-')}</span>
            <span>${escapeHtml(task.result.outputPath || task.result.mergedOutputPath || '-')}</span>
            <div class="info-actions">
                <button class="btn btn-secondary" onclick="viewTaskDetails('${escapeHtml(task.taskId)}')">任务详情</button>
                <button class="btn btn-primary" onclick="openPublicationModal('${escapeHtml(task.result.artifactId)}')">${publishedArtifactIds.has(task.result.artifactId) ? '再次发布' : '立即发布'}</button>
            </div>
        </div>
    `).join('');

    const artifactCards = (artifacts || []).slice(0, 6).map(item => `
        <div class="info-item">
            <label>${escapeHtml(item.artifactId || 'unknown')}</label>
            <span>${escapeHtml(item.artifactType || 'unknown')}</span>
            <span>${escapeHtml(item.outputPath || '-')}</span>
            <div class="info-actions">
                <button class="btn btn-secondary" onclick="showArtifactManifest('${escapeHtml(item.artifactId || '')}')">Manifest</button>
                <button class="btn btn-primary" onclick="openPublicationModal('${escapeHtml(item.artifactId || '')}')">发布</button>
            </div>
        </div>
    `).join('');

    const publicationCards = (publications || []).slice(0, 6).map(item => `
        <div class="info-item">
            <label>${escapeHtml(item.publicationId || 'unknown')}</label>
            <span>${escapeHtml(item.alias || item.artifactId || '-')}</span>
            <span>${escapeHtml(item.publishPath || '-')}</span>
            <div class="info-actions">
                <button class="btn btn-secondary" onclick="showPublicationDetails('${escapeHtml(item.publicationId || '')}')">查看</button>
            </div>
        </div>
    `).join('');

    return `
        <div class="release-panel-section">
            <h4>从已完成任务直接发布</h4>
            ${taskCards ? `<div class="info-list">${taskCards}</div>` : '<div class="message info">暂无已完成且已生成产物的任务</div>'}
        </div>
        <div class="release-panel-section">
            <h4>可发布产物</h4>
            ${artifactCards ? `<div class="info-list">${artifactCards}</div>` : '<div class="message info">暂无产物</div>'}
        </div>
        <div class="release-panel-section">
            <h4>最近发布</h4>
            ${publicationCards ? `<div class="info-list">${publicationCards}</div>` : '<div class="message info">暂无发布记录</div>'}
        </div>
    `;
}

async function refreshTaskReleasePanel(taskData = null) {
    const panel = document.getElementById('taskReleasePanel');
    if (!panel) return;
    panel.innerHTML = '<div class="loading">加载发布工作台...</div>';
    try {
        const [artifactsResponse, publicationsResponse, tasksResponse] = await Promise.all([
            terraForgeAPI.listArtifacts(),
            terraForgeAPI.listPublications(),
            taskData ? Promise.resolve(taskData) : terraForgeAPI.getAllTasks()
        ]);
        panel.innerHTML = renderTaskReleaseActions(
            artifactsResponse?.artifacts || [],
            publicationsResponse?.publications || [],
            tasksResponse || {}
        );
    } catch (error) {
        panel.innerHTML = `<div class="message error">加载发布工作台失败: ${escapeHtml(error.message)}</div>`;
    }
}

// 更新任务列表
function updateTaskList(data) {
    const container = document.getElementById('taskList');
    if (!data || !data.tasks) {
        container.innerHTML = '<div class="message info">暂无任务</div>';
        return;
    }
    
    const tasks = Object.values(data.tasks);
    if (tasks.length === 0) {
        container.innerHTML = '<div class="message info">暂无任务</div>';
        return;
    }
    
    // 按任务ID（时间戳）降序排序，最新的任务在上面
    tasks.sort((a, b) => {
        // 提取任务ID中的时间戳部分进行比较
        const getTimestamp = (taskId) => {
            const match = taskId.match(/\d+$/);
            return match ? parseInt(match[0]) : 0;
        };
        return getTimestamp(b.taskId) - getTimestamp(a.taskId);
    });

    const html = tasks.map(task => {
        const progress = Math.max(0, Math.min(100, task.progress || 0));
        const statusText = getStatusText(task.status);
        const taskTime = getTaskDisplayTime(task);
        const stageText = task.currentStage || inferTaskStage(task);

        return `
            <div class="task-item task-item-${task.status}">
                <div class="task-head">
                    <div class="task-status-badge task-status-badge-${task.status}">
                        <span class="task-status ${task.status}"></span>
                        <span class="task-status-text">${statusText}</span>
                    </div>
                    <div class="task-id">${task.taskId}</div>
                    <div class="task-time">${taskTime}</div>
                </div>
                <div class="task-message">${task.message || '无消息'}</div>
                <div class="task-progress-row">
                    <div class="task-progress">
                        <div class="task-progress-bar" style="width: ${progress}%"></div>
                    </div>
                    <div class="task-progress-value">${progress}%</div>
                </div>
                <div class="task-footer">
                    <div class="task-meta">
                        <span class="task-chip">${stageText}</span>
                    </div>
                    <div class="task-actions">
                        <button class="btn btn-secondary" onclick="viewTaskDetails('${task.taskId}')" title="查看详情">
                            ${renderIcon('view', 'btn-icon')}查看
                        </button>
                        ${task.status === 'completed' && task.result?.artifactId ?
                            `<button class="btn btn-primary" onclick="openPublicationModal('${task.result.artifactId}')" title="发布产物">
                                发布
                            </button>` :
                            ''
                        }
                        ${task.status === 'running' ? 
                            `<button class="btn btn-warning" onclick="stopTask('${task.taskId}')" title="停止任务">
                                ${renderIcon('stop', 'btn-icon')}停止
                            </button>` : 
                            `<button class="btn btn-danger" onclick="deleteTask('${task.taskId}')" title="删除任务">
                                ${renderIcon('trash', 'btn-icon')}删除
                            </button>`
                        }
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

function getTaskDisplayTime(task) {
    const rawTime = task.endTime || task.startTime;
    if (rawTime) {
        try {
            return new Date(rawTime).toLocaleString('zh-CN');
        } catch (error) {
            return rawTime;
        }
    }

    const match = (task.taskId || '').match(/\d+$/);
    if (!match) {
        return '时间未知';
    }

    const timestamp = parseInt(match[0], 10);
    const millis = match[0].length === 10 ? timestamp * 1000 : timestamp;
    return new Date(millis).toLocaleString('zh-CN');
}

function inferTaskStage(task) {
    if (task.status === 'running') {
        return '任务执行中';
    }
    if (task.status === 'completed') {
        return '任务已完成';
    }
    if (task.status === 'failed') {
        return '等待处理失败原因';
    }
    if (task.status === 'stopped') {
        return '任务已被手动停止';
    }
    return '等待任务状态更新';
}

// 查看任务详情
async function viewTaskDetails(taskId) {
    try {
        const task = await terraForgeAPI.getTaskStatus(taskId);
        const eventsResponse = await terraForgeAPI.getTaskEvents(taskId).catch(() => null);
        const taskEvents = eventsResponse?.events || [];
        console.log('任务详情数据:', task); // 调试用
        
        // 处理消息换行
        let displayMessage = task.message || '无消息';
        displayMessage = displayMessage.replace(/,\s*/g, ',\n').replace(/。\s*/g, '。\n');
        
        // 格式化时间显示
        const formatTime = (timeStr) => {
            if (!timeStr) return '未知';
            try {
                return new Date(timeStr).toLocaleString('zh-CN');
            } catch (e) {
                return timeStr;
            }
        };
        
        const statusKey = task.status || 'unknown';
        const statusText = getStatusText(statusKey);
        const statusClass = `task-detail-status-${statusKey}`;

        let detailsHtml = `
            <div class="task-detail-wrap">
                <div class="task-detail-grid">
                    <div class="task-detail-row">
                        <span class="task-detail-label">任务ID</span>
                        <span class="task-detail-value">${task.taskId || taskId}</span>
                    </div>
                    <div class="task-detail-row">
                        <span class="task-detail-label">状态</span>
                        <span class="task-detail-status ${statusClass}">${statusText}</span>
                    </div>
                    <div class="task-detail-row">
                        <span class="task-detail-label">进度</span>
                        <span class="task-detail-value">${task.progress || 0}%</span>
                    </div>
                    <div class="task-detail-row">
                        <span class="task-detail-label">当前阶段</span>
                        <span class="task-detail-value">${task.currentStage || '未知'}</span>
                    </div>
                    <div class="task-detail-row">
                        <span class="task-detail-label">开始时间</span>
                        <span class="task-detail-value">${formatTime(task.startTime)}</span>
                    </div>
                    ${task.endTime ? `
                        <div class="task-detail-row">
                            <span class="task-detail-label">结束时间</span>
                            <span class="task-detail-value">${formatTime(task.endTime)}</span>
                        </div>
                    ` : ''}
                </div>

                <div class="task-detail-block">
                    <div class="task-detail-block-title">消息</div>
                    <div class="task-detail-message">${displayMessage}</div>
                </div>
            `;

        if (task.result && task.status === 'completed') {
            const resultRows = [];
            if (task.result.totalFiles) {
                resultRows.push(`<div class="task-detail-kv"><span>总文件数</span><span>${task.result.totalFiles}</span></div>`);
            }
            if (task.result.completedFiles !== undefined) {
                resultRows.push(`<div class="task-detail-kv"><span>成功处理</span><span>${task.result.completedFiles}</span></div>`);
            }
            if (task.result.failedFiles !== undefined) {
                resultRows.push(`<div class="task-detail-kv"><span>失败文件</span><span>${task.result.failedFiles}</span></div>`);
            }
            if (task.result.totalTerrainFiles) {
                resultRows.push(`<div class="task-detail-kv"><span>生成瓦片</span><span>${task.result.totalTerrainFiles}</span></div>`);
            }
            if (task.result.outputPath) {
                resultRows.push(`<div class="task-detail-kv"><span>输出路径</span><span>${task.result.outputPath}</span></div>`);
            }
            if (task.result.mergedOutputPath) {
                resultRows.push(`<div class="task-detail-kv"><span>合并输出</span><span>${task.result.mergedOutputPath}</span></div>`);
            }
            if (task.result.deletedNodataTiles !== undefined) {
                resultRows.push(`<div class="task-detail-kv"><span>删除透明瓦片</span><span>${task.result.deletedNodataTiles}</span></div>`);
            }
            if (task.result.method) {
                resultRows.push(`<div class="task-detail-kv"><span>处理方式</span><span>${task.result.method}</span></div>`);
            }
            if (task.result.artifactId) {
                resultRows.push(`<div class="task-detail-kv"><span>产物ID</span><span>${task.result.artifactId}</span></div>`);
            }
            if (task.stats?.processedTiles !== undefined) {
                resultRows.push(`<div class="task-detail-kv"><span>已处理瓦片</span><span>${task.stats.processedTiles}</span></div>`);
            }
            if (task.stats?.totalTiles !== undefined) {
                resultRows.push(`<div class="task-detail-kv"><span>总瓦片数</span><span>${task.stats.totalTiles}</span></div>`);
            }
            if (task.stats?.successRate) {
                resultRows.push(`<div class="task-detail-kv"><span>成功率</span><span>${task.stats.successRate}</span></div>`);
            }

            detailsHtml += `
                <div class="task-detail-block">
                    <div class="task-detail-block-title">任务结果</div>
                    <div class="task-detail-result">
                        ${resultRows.join('')}
                    </div>
                </div>
            `;
        }

        if (task.processLog && task.processLog.length > 0) {
            const recentLogs = task.processLog.slice(-20);
            const logItems = recentLogs.map(log => {
                const logTime = formatTime(log.timestamp);
                const progress = log.progress || 0;
                const stage = log.stage || '处理中';
                const message = log.message || '';
                const logState = log.status || 'running';
                const logStateText = getStatusText(logState);
                return `
                    <div class="task-log-item">
                        <div class="task-log-head">
                            <span class="task-log-state task-log-state-${logState}">${logStateText}</span>
                            <span class="task-log-stage">${stage}</span>
                            <span class="task-log-progress">${progress}%</span>
                        </div>
                        <div class="task-log-message">${message}</div>
                        <div class="task-log-time">${logTime}</div>
                    </div>
                `;
            }).join('');

            detailsHtml += `
                <div class="task-detail-block">
                    <div class="task-detail-block-title">处理日志</div>
                    <div class="task-log-list">
                        ${logItems}
                    </div>
                    ${task.processLog.length > 20 ? `
                        <div class="task-log-summary">显示最后20条日志，共${task.processLog.length}条</div>
                    ` : ''}
                </div>
            `;
        }

        if (Array.isArray(taskEvents) && taskEvents.length > 0) {
            const eventItems = taskEvents.slice(0, 50).map(evt => {
                const evtAt = formatTime(evt.eventAt || evt.createdAt || evt.timestamp);
                const evtType = escapeHtml(evt.eventType || evt.type || 'event');
                const details = evt.details ? escapeHtml(JSON.stringify(evt.details, null, 2)) : '';
                return `
                    <div class="task-log-item">
                        <div class="task-log-head">
                            <span class="task-log-stage">${evtType}</span>
                            <span class="task-log-time">${evtAt}</span>
                        </div>
                        <div class="task-log-message">${details || '无详情'}</div>
                    </div>
                `;
            }).join('');

            detailsHtml += `
                <div class="task-detail-block">
                    <div class="task-detail-block-title">事件流（最多显示 50 条）</div>
                    <div class="task-log-list">
                        ${eventItems}
                    </div>
                </div>
            `;
        }

        detailsHtml += `</div>`;
        
        showModal('任务详情', detailsHtml);
    } catch (error) {
        console.error('获取任务详情失败:', error);
        showMessage('获取任务详情失败', 'error');
    }
}

// 辅助函数：获取状态颜色
function getStatusColor(status) {
    switch (status) {
        case 'completed': return '#28a745';
        case 'running': return '#ffc107';
        case 'queued': return '#17a2b8';
        case 'failed': return '#dc3545';
        case 'stopped': return '#6c757d';
        default: return '#333';
    }
}

async function loadToolsData() {
    await Promise.allSettled([
        refreshArtifactsPanel(),
        refreshPublicationsPanel()
    ]);
}

// 辅助函数：获取状态文本
function getStatusText(status) {
    switch (status) {
        case 'completed': return '已完成';
        case 'running': return '运行中';
        case 'queued': return '排队中';
        case 'failed': return '失败';
        case 'stopped': return '已停止';
        default: return status || '未知';
    }
}

// 停止任务
async function stopTask(taskId) {
    if (!confirm('确定要停止这个任务吗？')) {
        return;
    }
    
    try {
        await terraForgeAPI.stopTask(taskId);
        showMessage('任务停止指令已发送', 'success');
        loadTasks(); // 重新加载任务列表
    } catch (error) {
        console.error('停止任务失败:', error);
        showMessage('停止任务失败', 'error');
    }
}

// 删除任务
async function deleteTask(taskId) {
    if (!confirm('确定要删除这个任务吗？删除后将无法恢复任务信息。')) {
        return;
    }
    
    try {
        await terraForgeAPI.deleteTask(taskId);
        showMessage('任务已删除', 'success');
        loadTasks(); // 重新加载任务列表
    } catch (error) {
        console.error('删除任务失败:', error);
        showMessage('删除任务失败', 'error');
    }
}

// 文件选择器
function selectFile(inputId) {
    filePickerCallback = function(path) {
        document.getElementById(inputId).value = path;
    };
    
    showModal('选择文件', `
        <div id="filePickerContent">
            <div class="file-browser">
                <div class="breadcrumb" id="pickerBreadcrumb">
                    <span class="breadcrumb-item active">根目录</span>
                </div>
                <div class="file-list" id="pickerFileList">
                    <div class="loading">加载中...</div>
                </div>
            </div>
        </div>
    `);
    
    loadPickerDatasources('');
}

// 在文件选择器中加载数据源
async function loadPickerDatasources(path = '') {
    try {
        const data = await terraForgeAPI.browseDatasources(path);
        updatePickerFileList(data, path);
    } catch (error) {
        console.error('文件选择器数据加载失败:', error);
        document.getElementById('pickerFileList').innerHTML = '<div class="message error">加载失败</div>';
    }
}

// 更新文件选择器文件列表
function updatePickerFileList(data, currentPath) {
    const container = document.getElementById('pickerFileList');
    if (!data) {
        container.innerHTML = '<div class="message error">加载失败</div>';
        return;
    }
    
    let html = '';
    
    // 返回上级目录
    if (currentPath) {
        const parentPath = currentPath.split('/').slice(0, -1).join('/');
        html += `
            <div class="file-item" onclick="loadPickerDatasources('${parentPath}')">
                ${renderIcon('back', 'file-icon')}
                <div class="file-info">
                    <div class="file-name">返回上级</div>
                </div>
            </div>
        `;
    }
    
    // 添加目录
    if (data.directories) {
        data.directories.forEach(dir => {
            const fullPath = currentPath ? `${currentPath}/${dir.name}` : dir.name;
            html += `
                <div class="file-item" onclick="loadPickerDatasources('${fullPath}')">
                    ${renderIcon('folder', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name">${dir.name}</div>
                    </div>
                </div>
            `;
        });
    }
    
    // 添加文件
    if (data.datasources) {
        data.datasources.forEach(file => {
            const fullPath = currentPath ? `${currentPath}/${file.name}` : file.name;
            html += `
                <div class="file-item" onclick="selectDatasource('${fullPath}')">
                    ${renderIcon('file', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name">${file.name}</div>
                    </div>
                    <div class="file-actions">
                        <button class="btn btn-primary" onclick="selectDatasource('${fullPath}')">选择</button>
                    </div>
                </div>
            `;
        });
    }
    
    container.innerHTML = html || '<div class="message info">目录为空</div>';
}

// 表单事件初始化
function initializeFormEvents() {
    initializeMapBandSelectors();

    // 监听文件选择状态，控制智能推荐按钮
    initializeRecommendButtons();
    
    // 地图切片表单
    const mapForm = document.getElementById('mapTileForm');
    if (mapForm) {
        mapForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const folderPaths = document.getElementById('mapFolderPaths').value;
            const filePatterns = document.getElementById('mapFilePatterns').value;
            const outputPath = document.getElementById('mapOutputPath').value;
            
            if (!folderPaths || !outputPath) {
                showMessage('请填写所有必填字段', 'warning');
                return;
            }
            
            try {
                const params = {
                    folderPaths: folderPaths.split(',').map(p => p.trim()),
                    filePatterns: filePatterns.split(',').map(p => p.trim()),
                    outputPath: outputPath, // 改为字符串，后端处理分割
                    minZoom: parseInt(document.getElementById('mapMinZoom').value),
                    maxZoom: parseInt(document.getElementById('mapMaxZoom').value),
                    tileSize: parseInt(document.getElementById('mapTileSize').value),
                    processes: parseInt(document.getElementById('mapProcesses').value),
                    threads: parseInt(document.getElementById('mapThreads').value),
                    maxMemory: document.getElementById('mapMaxMemory').value,
                    resampling: document.getElementById('mapResampling').value,
                    projection: document.getElementById('mapProjection').value,
                    dataFormat: document.getElementById('mapDataFormat').value,
                    imageFormat: document.getElementById('mapImageFormat').value,
                    tileScheme: document.getElementById('mapTileScheme').value,
                    redBand: parseInt(document.getElementById('mapRedBand').value),
                    greenBand: parseInt(document.getElementById('mapGreenBand').value),
                    blueBand: parseInt(document.getElementById('mapBlueBand').value),
                    nodataValue: document.getElementById('mapNodataValue').value ? parseFloat(document.getElementById('mapNodataValue').value) : null,
                    srcNodataValue: document.getElementById('mapSrcNodataValue').value ? parseFloat(document.getElementById('mapSrcNodataValue').value) : null,
                    dstNodataValue: document.getElementById('mapDstNodataValue').value ? parseFloat(document.getElementById('mapDstNodataValue').value) : null,
                    stretchType: document.getElementById('mapStretchType').value,
                    stretchLowPercent: parseFloat(document.getElementById('mapStretchLowPercent').value),
                    stretchHighPercent: parseFloat(document.getElementById('mapStretchHighPercent').value),
                    jpegQuality: parseInt(document.getElementById('mapJpegQuality').value),
                    pngCompression: parseInt(document.getElementById('mapPngCompression').value),
                    bandMismatchPolicy: document.getElementById('mapBandMismatchPolicy').value,
                    transparencyThreshold: (() => {
                        const value = parseFloat(document.getElementById('mapTransparencyThreshold').value);
                        return Number.isFinite(value) ? value : 0.1;
                    })(),
                    generateShpIndex: document.getElementById('mapGenerateShpIndex').checked,
                    enableIncrementalUpdate: document.getElementById('mapEnableIncrementalUpdate').checked,
                    skipNodataTiles: document.getElementById('mapSkipNodataTiles').checked
                };
                
                const result = await terraForgeAPI.createIndexedTiles(params);
                showMessage(`地图切片任务已启动: ${result.taskId}`, 'success');
                switchSection('tasks');
            } catch (error) {
                console.error('地图切片失败:', error);
                showMessage('地图切片失败', 'error');
            }
        });
    }
    
    // 地形切片表单
    const terrainForm = document.getElementById('terrainTileForm');
    if (terrainForm) {
        terrainForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const folderPaths = document.getElementById('terrainFolderPaths').value;
            const filePatterns = document.getElementById('terrainFilePatterns').value;
            const outputPath = document.getElementById('terrainOutputPath').value;
            
            if (!outputPath) {
                showMessage('请填写输出路径', 'warning');
                return;
            }
            
            try {
                // 处理地理边界
                const boundsStr = document.getElementById('terrainBounds').value;
                let bounds = null;
                if (boundsStr && boundsStr.trim()) {
                    bounds = boundsStr.split(',').map(b => parseFloat(b.trim()));
                    if (bounds.length !== 4) {
                        showMessage('地理边界格式错误，应为：west,south,east,north', 'warning');
                        return;
                    }
                }
                
                const params = {
                    folderPaths: folderPaths ? folderPaths.split(',').map(p => p.trim()) : [""],
                    filePatterns: filePatterns ? filePatterns.split(',').map(p => p.trim()) : ["*.tif"],
                    outputPath: outputPath, // 改为字符串，后端处理分割
                    startZoom: parseInt(document.getElementById('terrainStartZoom').value),
                    endZoom: parseInt(document.getElementById('terrainEndZoom').value),
                    maxTriangles: parseInt(document.getElementById('terrainMaxTriangles').value),
                    bounds: bounds,
                    compression: document.getElementById('terrainCompression').checked,
                    decompress: document.getElementById('terrainDecompress').checked,
                    threads: parseInt(document.getElementById('terrainThreads').value),
                    maxMemory: document.getElementById('terrainMaxMemory').value,
                    autoZoom: document.getElementById('terrainAutoZoom').checked,
                    zoomStrategy: document.getElementById('terrainZoomStrategy').value,
                    mergeTerrains: document.getElementById('terrainMerge').checked
                };
                
                const result = await terraForgeAPI.createTerrainTiles(params);
                showMessage(`地形切片任务已启动: ${result.taskId}`, 'success');
                switchSection('tasks');
            } catch (error) {
                console.error('地形切片失败:', error);
                showMessage('地形切片失败', 'error');
            }
        });
    }
}

// 初始化智能推荐按钮状态
function initializeRecommendButtons() {
    // 监听地图切片文件匹配模式变化
    const mapFolderPaths = document.getElementById('mapFolderPaths');
    const mapFilePatterns = document.getElementById('mapFilePatterns');
    const mapRecommendBtn = document.getElementById('mapRecommendBtn');
    
    if (mapFilePatterns && mapRecommendBtn) {
        // 初始状态检查
        updateRecommendButtonState('map');
        scheduleRefreshMapBandOptions();
        
        // 监听输入变化
        mapFilePatterns.addEventListener('input', () => {
            updateRecommendButtonState('map');
            scheduleRefreshMapBandOptions();
        });
        mapFilePatterns.addEventListener('change', () => {
            updateRecommendButtonState('map');
            scheduleRefreshMapBandOptions();
        });
    }

    if (mapFolderPaths) {
        mapFolderPaths.addEventListener('input', () => scheduleRefreshMapBandOptions());
        mapFolderPaths.addEventListener('change', () => scheduleRefreshMapBandOptions());
    }
    
    // 监听地形切片文件匹配模式变化
    const terrainFilePatterns = document.getElementById('terrainFilePatterns');
    const terrainRecommendBtn = document.getElementById('terrainRecommendBtn');
    
    if (terrainFilePatterns && terrainRecommendBtn) {
        // 初始状态检查
        updateRecommendButtonState('terrain');
        
        // 监听输入变化
        terrainFilePatterns.addEventListener('input', () => updateRecommendButtonState('terrain'));
        terrainFilePatterns.addEventListener('change', () => updateRecommendButtonState('terrain'));
    }
}

// 更新智能推荐按钮状态
function updateRecommendButtonState(type) {
    const inputField = type === 'map' ? 'mapFilePatterns' : 'terrainFilePatterns';
    const buttonId = type === 'map' ? 'mapRecommendBtn' : 'terrainRecommendBtn';
    
    const inputElement = document.getElementById(inputField);
    const buttonElement = document.getElementById(buttonId);
    
    if (inputElement && buttonElement) {
        const inputValue = inputElement.value.trim();
        
        // 按钮始终可点击，只是在点击时进行检查
        buttonElement.disabled = false;
        buttonElement.title = '点击获取智能推荐配置';
    }
}

function createMapBandSelectOptions(maxBandCount) {
    const safeMaxBandCount = Math.max(1, parseInt(maxBandCount, 10) || 1);
    const options = [];
    for (let band = 1; band <= safeMaxBandCount; band++) {
        options.push(`<option value="${band}">波段 ${band}</option>`);
    }
    return options.join('');
}

function setMapBandHint(message) {
    const hintElement = document.getElementById('mapBandSourceHint');
    if (hintElement) {
        hintElement.textContent = message;
    }
}

function setSingleBandSelectOptions(selectId, maxBandCount, preferredBand) {
    const selectElement = document.getElementById(selectId);
    if (!selectElement) {
        return;
    }

    const safeMaxBandCount = Math.max(1, parseInt(maxBandCount, 10) || 1);
    const previousValue = parseInt(selectElement.value, 10);
    const fallbackValue = Math.min(safeMaxBandCount, preferredBand);
    const nextValue = Number.isFinite(previousValue) && previousValue >= 1 && previousValue <= safeMaxBandCount
        ? previousValue
        : fallbackValue;

    selectElement.innerHTML = createMapBandSelectOptions(safeMaxBandCount);
    selectElement.value = String(nextValue);
}

function applyMapBandRange(maxBandCount) {
    setSingleBandSelectOptions('mapRedBand', maxBandCount, 1);
    setSingleBandSelectOptions('mapGreenBand', maxBandCount, 2);
    setSingleBandSelectOptions('mapBlueBand', maxBandCount, 3);
}

function initializeMapBandSelectors() {
    applyMapBandRange(16);
    setMapBandHint('支持自动读取：单个 tif 直接读取；多个 tif 按最小公共波段数。');
}

function parseMapFilePatterns() {
    const filePatternInput = document.getElementById('mapFilePatterns');
    if (!filePatternInput || !filePatternInput.value) {
        return [];
    }
    return filePatternInput.value
        .split(',')
        .map(item => item.trim())
        .filter(item => item.length > 0);
}

function parseMapFolderPaths() {
    const folderPathInput = document.getElementById('mapFolderPaths');
    if (!folderPathInput || !folderPathInput.value) {
        return [];
    }
    return folderPathInput.value
        .split(',')
        .map(item => item.trim())
        .filter(item => item.length > 0);
}

function isConcreteTifPath(filePath) {
    if (!filePath) {
        return false;
    }
    const lowerPath = filePath.toLowerCase();
    if (lowerPath.includes('*') || lowerPath.includes('?')) {
        return false;
    }
    if (lowerPath.endsWith('.txt')) {
        return false;
    }
    return lowerPath.endsWith('.tif') || lowerPath.endsWith('.tiff');
}

function extractBandCount(fileInfo) {
    const count = parseInt(fileInfo?.metadata?.bandCount, 10);
    if (!Number.isFinite(count) || count <= 0) {
        return null;
    }
    return count;
}

async function resolveMapBandSources() {
    const folderPaths = parseMapFolderPaths();
    const filePatterns = parseMapFilePatterns();

    if (folderPaths.length === 0) {
        return {
            success: false,
            reason: 'missing-folder-paths'
        };
    }

    if (filePatterns.length === 0) {
        return {
            success: false,
            reason: 'missing-file-patterns'
        };
    }

    const response = await terraForgeAPI.resolveDatasourceFiles({
        folderPaths,
        filePatterns,
        maxFiles: 200
    });

    if (!response || response.success === false) {
        return {
            success: false,
            reason: 'resolve-failed',
            error: response?.error || '解析文件失败'
        };
    }

    return {
        success: true,
        totalMatched: parseInt(response.totalMatched, 10) || 0,
        returnedCount: parseInt(response.returnedCount, 10) || 0,
        truncated: Boolean(response.truncated),
        files: Array.isArray(response.files) ? response.files : [],
        bandSummary: response.bandSummary || null
    };
}

function scheduleRefreshMapBandOptions() {
    if (mapBandDetectionTimer) {
        clearTimeout(mapBandDetectionTimer);
    }
    mapBandDetectionTimer = setTimeout(() => {
        refreshMapBandOptionsFromSelection(false);
    }, 300);
}

async function refreshMapBandOptionsFromSelection(showToastOnError = false) {
    const folderPaths = parseMapFolderPaths();
    const patterns = parseMapFilePatterns();

    if (folderPaths.length === 0) {
        applyMapBandRange(16);
        setMapBandHint('未选择数据源文件夹，当前为手动波段选择（1-16）。');
        if (showToastOnError) {
            showMessage('请先选择数据源文件夹', 'warning');
        }
        return;
    }

    if (patterns.length === 0) {
        applyMapBandRange(16);
        setMapBandHint('未选择文件模式，当前为手动波段选择（1-16）。');
        if (showToastOnError) {
            showMessage('请先选择具体 tif、通配符或 txt 文件列表', 'warning');
        }
        return;
    }

    try {
        const resolved = await resolveMapBandSources();
        if (!resolved.success) {
            applyMapBandRange(16);
            setMapBandHint('读取波段失败，已回退为手动波段选择（1-16）。');
            if (showToastOnError) {
                showMessage(resolved.error || '读取波段失败，已回退为手动选择', 'warning');
            }
            return;
        }

        const minCommonBandCount = parseInt(resolved.bandSummary?.commonBandCount, 10);
        if (!Number.isFinite(minCommonBandCount) || minCommonBandCount <= 0) {
            applyMapBandRange(16);
            setMapBandHint('匹配到了文件，但未读取到有效波段数，已回退为手动波段选择（1-16）。');
            if (showToastOnError) {
                showMessage('未读取到有效波段数，已回退为手动选择', 'warning');
            }
            return;
        }

        applyMapBandRange(minCommonBandCount);

        const summaryText = resolved.totalMatched === 1
            ? `已读取 1 个文件，可用波段数：${minCommonBandCount}。`
            : `已匹配 ${resolved.totalMatched} 个文件，按最小公共波段数 ${minCommonBandCount} 生成下拉。`;
        const truncatedText = resolved.truncated ? ' 当前仅统计前 200 个匹配文件。' : '';

        setMapBandHint(summaryText + truncatedText);
        if (showToastOnError) {
            showMessage(`已按最小公共波段数 ${minCommonBandCount} 更新下拉`, 'success');
        }
    } catch (error) {
        console.error('自动读取波段失败:', error);
        applyMapBandRange(16);
        setMapBandHint('自动读取波段失败，已回退为手动波段选择（1-16）。');
        if (showToastOnError) {
            showMessage('自动读取波段失败，请检查文件路径是否正确', 'warning');
        }
    }
}

// 智能推荐配置
async function getRecommendation(type) {
    const inputField = type === 'map' ? 'mapFilePatterns' : 'terrainFilePatterns';
    const filePatterns = document.getElementById(inputField).value.trim();
    
    if (!filePatterns) {
        showMessage('请先选择文件', 'warning');
        return;
    }
    
    // 检查是否包含通配符
    if (filePatterns.includes('*') || filePatterns.includes('?')) {
        showMessage('智能推荐不支持通配符，请选择具体的tif文件', 'warning');
        return;
    }
    
    // 检查是否包含txt文件（txt文件不支持智能推荐）
    if (filePatterns.includes('.txt')) {
        showMessage('智能推荐不支持txt文件，请只选择tif文件', 'warning');
        return;
    }
    
    // 检查是否包含具体的tif文件
    const hasSpecificTifFiles = filePatterns.includes('.tif') || filePatterns.includes('.tiff');
    
    if (!hasSpecificTifFiles) {
        showMessage('智能推荐只支持具体的tif文件', 'warning');
        return;
    }
    
    // 检查是否只有一个tif文件
    const files = filePatterns.split(',').map(f => f.trim()).filter(f => f.length > 0);
    const tifFiles = files.filter(f => f.endsWith('.tif') || f.endsWith('.tiff'));
    
    if (files.length > 1) {
        showMessage('智能推荐只支持单个tif文件，请只选择一个文件', 'warning');
        return;
    }
    
    if (tifFiles.length !== 1) {
        showMessage('智能推荐只支持单个tif文件', 'warning');
        return;
    }
    
    // 调用智能推荐接口
    try {
        const tifFile = tifFiles[0]; // 已经验证过只有一个tif文件
        showMessage('正在分析文件，请稍候...', 'info');
        
        // 调用配置推荐接口
        const configResponse = await terraForgeAPI.recommendConfig({ 
            sourceFile: tifFile, 
            tileType: type === 'map' ? 'map' : 'terrain' 
        });
        
        if (configResponse && configResponse.success && configResponse.recommendations) {
            showRecommendationModal(type, configResponse, tifFile);
        } else {
            showMessage('未能获取推荐配置，请手动设置参数', 'warning');
        }
    } catch (error) {
        console.error('智能推荐失败:', error);
        showMessage('智能推荐失败: ' + error.message, 'error');
    }
}

// 刷新仪表盘
async function refreshDashboard() {
    await loadDashboard();
}

// 刷新数据源
function refreshDatasource() {
    loadDatasources(currentDatasourcePath);
}

// 刷新任务列表
function refreshTasks() {
    loadTasks();
}

// 清理任务
async function cleanupTasks() {
    if (!confirm('确定要清理已完成的任务吗？')) return;
    
    try {
        await terraForgeAPI.cleanupTasks();
        showMessage('任务清理完成', 'success');
        loadTasks();
    } catch (error) {
        console.error('清理任务失败:', error);
        showMessage('清理任务失败', 'error');
    }
}

// 显示智能推荐结果弹框
function showRecommendationModal(type, configData, filename) {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    
    const typeText = type === 'map' ? '地图切片' : '地形切片';
    
    const recommendations = configData.recommendations;
    const systemInfo = configData.systemInfo;
    const fileSize = configData.fileSize;
    
    let recommendationHtml = `
        <div class="modal-content" style="max-width: 600px; max-height: 80vh; overflow-y: auto;">
            <div class="modal-header">
                <h3>智能推荐配置 - ${typeText}</h3>
                <span class="close" onclick="this.closest('.modal').remove()">&times;</span>
            </div>
            <div class="modal-body">
                <div style="margin-bottom: 15px;">
                    <strong>文件：</strong> ${filename} ${fileSize ? `(${fileSize.toFixed(2)} GB)` : ''}
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>系统信息：</strong> ${systemInfo ? `CPU ${systemInfo.cpuCount}核, 内存 ${systemInfo.memoryTotalGb.toFixed(1)}GB` : '系统信息不可用'}
                </div>
                <div style="margin-bottom: 20px;">
                    <h4>推荐配置：</h4>
                    <div class="recommendation-list">
    `;
    
    // 根据实际返回的推荐配置显示
    if (recommendations.minZoom !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>最小缩放级别：</strong> ${recommendations.minZoom}</div>`;
    }
    if (recommendations.maxZoom !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>最大缩放级别：</strong> ${recommendations.maxZoom}</div>`;
    }
    if (recommendations.processes !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>进程数：</strong> ${recommendations.processes}</div>`;
    }
    if (recommendations.maxMemory !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>最大内存：</strong> ${recommendations.maxMemory}</div>`;
    }
    if (recommendations.tileFormat !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>瓦片格式：</strong> ${recommendations.tileFormat}</div>`;
    }
    if (recommendations.quality !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>质量：</strong> ${recommendations.quality}</div>`;
    }
    if (recommendations.resampling !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>重采样方法：</strong> ${recommendations.resampling}</div>`;
    }
    if (recommendations.compression !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>压缩：</strong> ${recommendations.compression ? '是' : '否'}</div>`;
    }
    if (recommendations.decompress !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>解压：</strong> ${recommendations.decompress ? '是' : '否'}</div>`;
    }
    if (recommendations.autoZoom !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>智能分级：</strong> ${recommendations.autoZoom ? '是' : '否'}</div>`;
    }
    if (recommendations.zoomStrategy !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>分级策略：</strong> ${recommendations.zoomStrategy}</div>`;
    }
    if (recommendations.optimizeFile !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>文件优化：</strong> ${recommendations.optimizeFile ? '是' : '否'}</div>`;
    }
    if (recommendations.createOverview !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>创建概览：</strong> ${recommendations.createOverview ? '是' : '否'}</div>`;
    }
    if (recommendations.useOptimizedMode !== undefined) {
        recommendationHtml += `<div class="recommendation-item"><strong>优化模式：</strong> ${recommendations.useOptimizedMode ? '是' : '否'}</div>`;
    }
    
    recommendationHtml += `
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-primary" onclick="this.closest('.modal').remove()">确定</button>
            </div>
        </div>
    `;
    
    modal.innerHTML = recommendationHtml;
    document.body.appendChild(modal);
}

// 新建文件夹
async function createFolder() {
    const folderName = prompt('请输入新文件夹名称');
    if (!folderName) return;
    const folderPath = currentWorkspacePath ? `${currentWorkspacePath}/${folderName}` : folderName;
    console.log('新建文件夹完整路径:', folderPath);
    try {
        await terraForgeAPI.createWorkspaceFolder(folderPath);
        // 创建后刷新当前目录
        await loadWorkspaceFiles(currentWorkspacePath);
        showMessage('文件夹创建成功', 'success');
    } catch (error) {
        showMessage('文件夹创建失败: ' + error.message, 'error');
    }
}

// 删除工作空间项目
async function deleteWorkspaceItem(path, type) {
    if (!confirm(`确定要删除这个${type === 'folder' ? '文件夹' : '文件'}吗？`)) return;
    
    try {
        console.log('开始删除操作:', { path, type });
        
        if (type === 'folder') {
            const response = await terraForgeAPI.deleteWorkspaceFolder(path);
            console.log('删除文件夹响应:', response);
        } else {
            const response = await terraForgeAPI.deleteWorkspaceFile(path);
            console.log('删除文件响应:', response);
        }
        
        showMessage('删除成功', 'success');
        
        // 获取当前路径
        const currentPath = path.split('/').slice(0, -1).join('/');
        console.log('重新加载目录:', currentPath);
        
        // 重新加载当前目录
        await loadWorkspaceFiles(currentPath);
    } catch (error) {
        console.error('删除失败:', error);
        showMessage(`删除失败: ${error.message}`, 'error');
    }
}

async function renameWorkspaceItem(path, type) {
    const currentName = (path || '').split('/').filter(Boolean).slice(-1)[0] || '';
    const newName = prompt('请输入新名称', currentName);
    if (!newName || !newName.trim()) return;

    try {
        if (type === 'folder') {
            await terraForgeAPI.renameWorkspaceFolder(path, newName.trim());
        } else {
            await terraForgeAPI.renameWorkspaceFile(path, newName.trim());
        }
        showMessage('重命名成功', 'success');
        await loadWorkspaceFiles(path.split('/').slice(0, -1).join('/'));
    } catch (error) {
        showMessage(`重命名失败: ${error.message}`, 'error');
    }
}

function openWorkspaceFolderPicker(onPicked) {
    filePickerCallback = (path, isDir) => {
        if (!isDir) {
            showMessage('请选择文件夹', 'warning');
            return;
        }
        if (typeof onPicked === 'function') {
            onPicked(path);
        }
    };

    let modal = document.getElementById('filePickerModal');
    if (!modal) {
        createFilePickerModal(true);
        modal = document.getElementById('filePickerModal');
    }
    modal.style.display = 'block';
    loadPickerFileList('');
}

function moveWorkspaceItemPrompt(sourcePath) {
    if (!sourcePath) return;

    openWorkspaceFolderPicker(async (targetFolder) => {
        const baseName = (sourcePath || '').split('/').filter(Boolean).slice(-1)[0] || '';
        const targetName = prompt('目标名称（可改名）', baseName);
        if (!targetName || !targetName.trim()) return;

        const normalizedFolder = (targetFolder || '').trim().replace(/^\/+|\/+$/g, '');
        const normalizedName = targetName.trim().replace(/^\/+|\/+$/g, '');
        const targetPath = normalizedFolder ? `${normalizedFolder}/${normalizedName}` : normalizedName;

        if (targetPath === sourcePath) {
            showMessage('目标路径不能与源路径相同', 'warning');
            return;
        }
        if (targetPath.startsWith(`${sourcePath}/`)) {
            showMessage('不能移动到自身子目录内', 'warning');
            return;
        }

        try {
            await terraForgeAPI.moveWorkspaceItem(sourcePath, targetPath);
            showMessage('移动成功', 'success');
            await loadWorkspaceFiles(sourcePath.split('/').slice(0, -1).join('/'));
        } catch (error) {
            showMessage(`移动失败: ${error.message}`, 'error');
        }
    });
}



// 工具函数
function showTileConverter() {
    switchSection('tools', { subsectionId: 'toolTileConverter', toolsTab: 'ops' });
}

function showNodataScanner() {
    switchSection('tools', { subsectionId: 'toolNodataTiles', toolsTab: 'quality' });
}

function showLayerUpdater() {
    switchSection('tools', { subsectionId: 'toolLayerJson', toolsTab: 'quality' });
}

function renderPreflightSummary(result) {
    const warningCount = result?.warnings?.length || 0;
    const errorCount = result?.errors?.length || 0;
    const estimate = result?.estimate || {};
    return `
        <div class="info-list">
            <div class="info-row">
                <span class="info-label">检查状态</span>
                <span class="info-value">${result.success ? '可进入构建' : '存在风险/错误'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">匹配文件</span>
                <span class="info-value">${result.matchedFileCount || 0}</span>
            </div>
            <div class="info-row">
                <span class="info-label">预计瓦片数</span>
                <span class="info-value">${estimate.tileCount || 0}</span>
            </div>
            <div class="info-row">
                <span class="info-label">预估耗时</span>
                <span class="info-value">${estimate.durationSeconds || 0} 秒</span>
            </div>
            <div class="info-row">
                <span class="info-label">警告 / 错误</span>
                <span class="info-value">${warningCount} / ${errorCount}</span>
            </div>
        </div>
        <div class="tool-actions">
            <button class="btn btn-secondary" onclick="showPreflightReport()">查看详情</button>
        </div>
    `;
}

function showPreflightReport() {
    const result = window.lastPreflightResult;
    if (!result) {
        showMessage('暂无预检查结果', 'warning');
        return;
    }

    const fileRows = (result.files || []).slice(0, 20).map(file => `
        <div class="info-row">
            <span class="info-label">${escapeHtml(file.path || 'unknown')}</span>
            <span class="info-value">${file.error ? escapeHtml(file.error) : `${file.width || 0} x ${file.height || 0} / ${file.bandCount || 0} 波段`}</span>
        </div>
    `).join('');

    const body = `
        <div class="task-detail-wrap">
            <div class="task-detail-block">
                <div class="task-detail-block-title">总体检查</div>
                <div class="info-list">
                    <div class="info-row"><span class="info-label">任务类型</span><span class="info-value">${escapeHtml(result.jobType || '')}</span></div>
                    <div class="info-row"><span class="info-label">输入准备</span><span class="info-value">${result.checks?.inputsReady ? '通过' : '失败'}</span></div>
                    <div class="info-row"><span class="info-label">工具链</span><span class="info-value">${result.checks?.toolchainReady ? '可用' : '不可用'}</span></div>
                    <div class="info-row"><span class="info-label">投影一致性</span><span class="info-value">${result.checks?.projectionConsistent ? '一致' : '不一致'}</span></div>
                    <div class="info-row"><span class="info-label">输出覆盖风险</span><span class="info-value">${result.checks?.outputOverwriteRisk ? '存在' : '无'}</span></div>
                </div>
            </div>
            <div class="task-detail-block">
                <div class="task-detail-block-title">警告</div>
                <pre>${escapeHtml((result.warnings || []).join('\n') || '无')}</pre>
            </div>
            <div class="task-detail-block">
                <div class="task-detail-block-title">错误</div>
                <pre>${escapeHtml((result.errors || []).join('\n') || '无')}</pre>
            </div>
            <div class="task-detail-block">
                <div class="task-detail-block-title">扫描文件</div>
                <div class="info-list">${fileRows || '<div class="message info">暂无文件明细</div>'}</div>
            </div>
        </div>
    `;
    showModal('预检查报告', body);
}

async function runPreflightTool() {
    const panel = document.getElementById('preflightResult');
    panel.innerHTML = '<div class="loading">预检查执行中...</div>';

    try {
        const params = {
            jobType: document.getElementById('preflightJobType').value,
            folderPaths: parseCommaList(document.getElementById('preflightFolderPaths').value),
            filePatterns: parseCommaList(document.getElementById('preflightFilePatterns').value),
            outputPath: document.getElementById('preflightOutputPath').value.trim(),
            minZoom: parseInt(document.getElementById('preflightMinZoom').value, 10),
            maxZoom: parseInt(document.getElementById('preflightMaxZoom').value, 10),
            maxFiles: parseInt(document.getElementById('preflightMaxFiles').value, 10),
        };
        const heightBand = document.getElementById('preflightHeightBand').value.trim();
        if (heightBand) {
            params.heightBand = parseInt(heightBand, 10);
        }

        const result = await terraForgeAPI.runPreflightCheck(params);
        window.lastPreflightResult = result;
        panel.innerHTML = renderPreflightSummary(result);
        showMessage(result.success ? '预检查完成' : '预检查已完成，请查看警告/错误', result.success ? 'success' : 'warning');
    } catch (error) {
        panel.innerHTML = `<div class="message error">预检查失败: ${escapeHtml(error.message)}</div>`;
        showMessage(`预检查失败: ${error.message}`, 'error');
    }
}

async function runSplitTool() {
    const panel = document.getElementById('splitResult');
    panel.innerHTML = '<div class="loading">正在提交拆分任务...</div>';

    try {
        const sourceFile = document.getElementById('splitSourceFile').value.trim();
        const outputPath = parseCommaList(document.getElementById('splitOutputFolderPaths').value)[0] || '';
        if (!sourceFile || !outputPath) {
            throw new Error('请先选择源文件和输出目录');
        }

        const result = await terraForgeAPI.splitLargeFile({
            sourceFile,
            outputPath,
            tileSize: parseInt(document.getElementById('splitTileSize').value, 10),
            overlap: parseInt(document.getElementById('splitOverlap').value, 10),
            maxFileSize: parseFloat(document.getElementById('splitMaxFileSize').value),
            namingPattern: document.getElementById('splitNamingPattern').value.trim()
        });

        if (result.skipSplit) {
            panel.innerHTML = `
                <div class="message info">
                    文件大小 ${escapeHtml(result.fileSize || '')} 未超过阈值 ${escapeHtml(result.threshold || '')}，无需拆分
                </div>
            `;
            showMessage('该文件当前无需拆分', 'info');
            return;
        }

        panel.innerHTML = `
            <div class="info-list">
                <div class="info-row"><span class="info-label">任务ID</span><span class="info-value">${escapeHtml(result.taskId || '')}</span></div>
                <div class="info-row"><span class="info-label">文件大小</span><span class="info-value">${escapeHtml(result.fileSize || '')}</span></div>
                <div class="info-row"><span class="info-label">输出目录</span><span class="info-value">${escapeHtml(result.outputPath || '')}</span></div>
            </div>
            <div class="tool-actions">
                <button class="btn btn-secondary" onclick="switchSection('tasks')">查看任务</button>
            </div>
        `;
        showMessage(`拆分任务已启动: ${result.taskId}`, 'success');
    } catch (error) {
        panel.innerHTML = `<div class="message error">拆分失败: ${escapeHtml(error.message)}</div>`;
        showMessage(`拆分失败: ${error.message}`, 'error');
    }
}

function renderArtifactCards(items) {
    return items.map(item => `
        <div class="info-item">
            <label>${escapeHtml(item.artifactId || 'unknown')}</label>
            <span>${escapeHtml(`${item.artifactType || 'unknown'} / ${item.format || 'unknown'}`)}</span>
            <span>${escapeHtml(item.outputPath || '-')}</span>
            <div class="info-actions">
                <button class="btn btn-secondary" onclick="showArtifactManifest('${escapeHtml(item.artifactId || '')}')">Manifest</button>
                <button class="btn btn-primary" onclick="openPublicationModal('${escapeHtml(item.artifactId || '')}')">发布</button>
            </div>
        </div>
    `).join('');
}

async function refreshArtifactsPanel() {
    const panel = document.getElementById('artifactsPanel');
    if (!panel) {
        return;
    }
    panel.innerHTML = '<div class="loading">加载产物中...</div>';

    try {
        const result = await terraForgeAPI.listArtifacts();
        const items = result.artifacts || [];
        panel.innerHTML = items.length > 0
            ? `<div class="info-list">${renderArtifactCards(items)}</div>`
            : '<div class="simple-info"><div class="placeholder-text">暂无产物记录</div></div>';
    } catch (error) {
        panel.innerHTML = `<div class="message error">加载产物失败: ${escapeHtml(error.message)}</div>`;
    }
}

async function showArtifactManifest(artifactId) {
    try {
        const result = await terraForgeAPI.getArtifactManifest(artifactId);
        showModal(`Manifest: ${artifactId}`, `<pre>${escapeHtml(JSON.stringify(result.manifest || {}, null, 2))}</pre>`);
    } catch (error) {
        showMessage(`读取 manifest 失败: ${error.message}`, 'error');
    }
}

function openPublicationModal(artifactId) {
    const body = `
        <div class="task-detail-wrap">
            <div class="form-group">
                <label>发布别名</label>
                <input type="text" id="publicationAlias" value="${escapeHtml(artifactId)}" placeholder="如 demo-map-v1">
            </div>
            <div class="form-group">
                <label>发布ID</label>
                <input type="text" id="publicationIdInput" placeholder="为空则自动按别名生成">
            </div>
            <div class="form-group">
                <label>发布类型</label>
                <select id="publicationType">
                    <option value="static" selected>static</option>
                </select>
            </div>
            <div class="form-group">
                <label>可见性</label>
                <select id="publicationVisibility">
                    <option value="private" selected>private</option>
                    <option value="internal">internal</option>
                    <option value="public">public</option>
                </select>
            </div>
            <div class="form-group">
                <label>备注</label>
                <textarea id="publicationNote" placeholder="记录发布说明"></textarea>
            </div>
        </div>
    `;
    const footer = `
        <button class="btn btn-secondary" onclick="closeModal()">取消</button>
        <button class="btn btn-primary" onclick="submitPublication('${escapeHtml(artifactId)}')">确认发布</button>
    `;
    showModal(`发布产物 ${artifactId}`, body, footer);
}

async function submitPublication(artifactId) {
    try {
        const alias = document.getElementById('publicationAlias').value.trim();
        const publicationId = document.getElementById('publicationIdInput').value.trim();
        const publishType = document.getElementById('publicationType').value;
        const visibility = document.getElementById('publicationVisibility').value;
        const note = document.getElementById('publicationNote').value.trim();

        const payload = {
            artifactId,
            alias,
            publishType,
            visibility,
            note
        };
        if (publicationId) {
            payload.publicationId = publicationId;
        }

        const result = await terraForgeAPI.createPublication(payload);
        closeModal();
        showMessage(`发布记录已创建: ${result.publication?.id || result.publication?.alias || alias}`, 'success');
        await Promise.allSettled([refreshArtifactsPanel(), refreshPublicationsPanel()]);
    } catch (error) {
        showMessage(`创建发布记录失败: ${error.message}`, 'error');
    }
}

function renderPublicationCards(items) {
    return items.map(item => `
        <div class="info-item">
            <label>${escapeHtml(item.publicationId || item.id || 'unknown')}</label>
            <span>${escapeHtml(`${item.alias || '-'} / ${item.publishType || '-'}`)}</span>
            <span>${escapeHtml(item.publishPath || '-')}</span>
            <div class="info-actions">
                <button class="btn btn-secondary" onclick="showPublicationDetails('${escapeHtml(item.publicationId || item.id || '')}')">详情</button>
            </div>
        </div>
    `).join('');
}

async function refreshPublicationsPanel() {
    const panel = document.getElementById('publicationsPanel');
    if (!panel) {
        return;
    }
    panel.innerHTML = '<div class="loading">加载发布记录中...</div>';

    try {
        const result = await terraForgeAPI.listPublications();
        const items = result.publications || [];
        panel.innerHTML = items.length > 0
            ? `<div class="info-list">${renderPublicationCards(items)}</div>`
            : '<div class="simple-info"><div class="placeholder-text">暂无发布记录</div></div>';
    } catch (error) {
        panel.innerHTML = `<div class="message error">加载发布记录失败: ${escapeHtml(error.message)}</div>`;
    }
}

async function showPublicationDetails(publicationId) {
    try {
        const result = await terraForgeAPI.getPublication(publicationId);
        showModal(`发布详情: ${publicationId}`, `<pre>${escapeHtml(JSON.stringify(result.publication || {}, null, 2))}</pre>`);
    } catch (error) {
        showMessage(`读取发布详情失败: ${error.message}`, 'error');
    }
}

// 开始定时任务
function startPeriodicTasks() {
    // 每30秒检查一次系统状态
    setInterval(checkSystemStatus, 30000);
}

// 通用UI工具函数
function showMessage(message, type = 'info') {
    const messageEl = document.createElement('div');
    messageEl.className = `toast-message message ${type}`;
    messageEl.innerHTML = `
        ${renderIcon(type, 'message-symbol')}
        <span>${message}</span>
        <button type="button" class="message-close" onclick="this.parentElement.remove()">&times;</button>
    `;

    document.body.appendChild(messageEl);
    
    // 3秒后自动消失
    setTimeout(() => {
        if (messageEl.parentElement) {
            messageEl.style.animation = 'tf-toast-up 0.3s ease-out forwards';
            setTimeout(() => messageEl.remove(), 300);
        }
    }, 3000);
}

function showLoading(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = '<div class="loading">加载中...</div>';
    }
}

function hideLoading(containerId) {
    const container = document.getElementById(containerId);
    if (container && container.querySelector('.loading')) {
        container.querySelector('.loading').remove();
    }
}

function showError(containerId, message) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<div class="message error">${message}</div>`;
    }
}

function showModal(title, body, footer = '') {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = body;
    document.getElementById('modalFooter').innerHTML = footer || `
        <button class="btn btn-secondary" onclick="closeModal()">关闭</button>
    `;
    document.getElementById('modal').style.display = 'block';
}

// 加载系统管理
async function loadSystemManagement() {
    try {
        // 初始加载更新信息
        document.getElementById('updateInfo').innerHTML = '<div class="message info">点击检查更新按钮获取最新信息</div>';
        document.getElementById('routesInfo').innerHTML = '<div class="message info">点击查看路由按钮获取API信息</div>';
    } catch (error) {
        console.error('系统管理信息加载失败:', error);
    }
}

// 检查更新
async function checkForUpdates() {
    try {
        document.getElementById('updateInfo').innerHTML = '<div class="loading">检查更新中...</div>';

        const [health, systemInfo, workspaceInfo, cacheInfo] = await Promise.all([
            terraForgeAPI.getHealthStatus(),
            terraForgeAPI.getSystemInfo(),
            terraForgeAPI.getWorkspaceInfo(),
            terraForgeAPI.getCacheInfo()
        ]);
        const currentVersion = health.version || systemInfo.version || '未知版本';
        const databaseStatus = health?.database?.status || 'unknown';
        const workspaceSummary = workspaceInfo?.workspaceInfo?.totalSizeFormatted || '0 B';
        const cacheDirectories = cacheInfo?.totalDirectories ?? 0;
        
        document.getElementById('updateInfo').innerHTML = `
            <div class="update-status">
                <div class="status-item">
                    <span class="status-label">当前版本</span>
                    <span class="status-value">${currentVersion}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">状态</span>
                    <span class="status-value">${health.status === 'healthy' ? '系统运行正常' : '系统部分降级'}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">最后检查</span>
                    <span class="status-value">${health.timestamp || new Date().toLocaleString()}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">数据库状态</span>
                    <span class="status-value">${databaseStatus}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">工作空间占用</span>
                    <span class="status-value">${workspaceSummary}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">缓存目录数</span>
                    <span class="status-value">${cacheDirectories}</span>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('检查更新失败:', error);
        document.getElementById('updateInfo').innerHTML = '<div class="message error">检查更新失败</div>';
    }
}

// 更新容器
async function updateContainer() {
    try {
        const updateParams = {
            updateType: "all",
            timezone: "Asia/Shanghai"
        };
        
        const result = await terraForgeAPI.updateContainer(updateParams);
        const updateResults = result.updateResults?.results || {};
        const flattenedActions = Object.entries(updateResults)
            .flatMap(([section, info]) => (info?.actions || []).map(action => `${section}: ${action}`));

        showMessage('容器信息更新已执行', 'success');

        document.getElementById('updateInfo').innerHTML = `
            <div class="update-status">
                <div class="status-item">
                    <span class="status-label">执行结果</span>
                    <span class="status-value">${result.message || '已完成'}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">执行时间</span>
                    <span class="status-value">${result.updateResults?.timestamp || new Date().toLocaleString()}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">更新时间区</span>
                    <span class="status-value">${updateParams.timezone}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">动作摘要</span>
                    <span class="status-value">${flattenedActions.length > 0 ? flattenedActions.join('；') : '无额外动作'}</span>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('容器更新失败:', error);
        showMessage(`容器更新失败: ${error.message}`, 'error');
    }
}

// 加载API路由
async function loadRoutes() {
    try {
        document.getElementById('routesInfo').innerHTML = '<div class="loading">加载中...</div>';
        
        const routes = await terraForgeAPI.getRoutes();
        
        // 如果返回的是字符串，尝试解析
        let routeData;
        if (typeof routes === 'string') {
            try {
                routeData = JSON.parse(routes);
            } catch {
                document.getElementById('routesInfo').innerHTML = `<pre style="white-space: pre-wrap;">${routes}</pre>`;
                return;
            }
        } else {
            routeData = routes;
        }
        
        // 如果是对象且有routes属性
        if (routeData && routeData.routes) {
            const routesList = routeData.routes.map(route => `
                <div class="route-item">
                    <span class="route-method">${Array.isArray(route.methods) ? route.methods.join('/') : (route.method || '-')}</span>
                    <span class="route-path">${route.path}</span>
                    <span class="route-desc">${route.category ? `[${route.category}] ` : ''}${route.description || ''}</span>
                </div>
            `).join('');
            
            document.getElementById('routesInfo').innerHTML = `
                <div class="routes-list">
                    ${routesList}
                </div>
                <div class="routes-summary">
                    总共 ${routeData.routes.length} 个API接口
                </div>
            `;
        } else {
            document.getElementById('routesInfo').innerHTML = `<pre style="white-space: pre-wrap;">${JSON.stringify(routeData, null, 2)}</pre>`;
        }
    } catch (error) {
        console.error('加载API路由失败:', error);
        document.getElementById('routesInfo').innerHTML = '<div class="message error">加载API路由失败</div>';
    }
}

// 日期时间更新
function startDateTimeUpdate() {
    updateDateTime();
    setInterval(updateDateTime, 1000);
}

function updateDateTime() {
    const now = new Date();
    const dateElement = document.getElementById('currentDate');
    const timeElement = document.getElementById('currentTime');
    
    if (dateElement && timeElement) {
        dateElement.textContent = now.toLocaleDateString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
        timeElement.textContent = now.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }
}

// 仪表盘自动刷新控制
function toggleAutoRefresh() {
    const toggle = document.getElementById('autoRefreshToggle');
    autoRefreshEnabled = toggle.checked;
    
    if (autoRefreshEnabled) {
        startAutoRefresh();
        showMessage('自动刷新已开启', 'success');
    } else {
        stopAutoRefresh();
        showMessage('自动刷新已关闭', 'info');
    }
}

function updateRefreshInterval() {
    const interval = document.getElementById('refreshInterval').value;
    if (autoRefreshEnabled) {
        stopAutoRefresh();
        startAutoRefresh();
        showMessage(`刷新间隔已更新为${interval}秒`, 'info');
    }
}

function startAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    
    const interval = document.getElementById('refreshInterval').value * 1000;
    autoRefreshInterval = setInterval(async () => {
        // 只在仪表盘页面激活时才自动刷新
        if (document.getElementById('dashboard').classList.contains('active')) {
            await updateSystemInfo();
        }
    }, interval);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

// 文件详情弹出框
function showFileDetails(filePath, fileName, browseType = 'datasource') {
    const loader = browseType === 'results'
        ? terraForgeAPI.getWorkspaceFileInfo(filePath)
        : terraForgeAPI.getFileInfo(filePath);

    loader.then(response => {
        console.log('Java API 原始响应:', response); // 详细调试
        console.log('文件路径:', filePath, '文件名:', fileName); // 调试参数
        
        // 现在Java API返回的是直接映射Python的结构
        const fileInfo = response;
        console.log('文件信息:', fileInfo);
        console.log('fileInfo.metadata:', fileInfo.metadata);
        console.log('fileInfo的类型:', typeof fileInfo);
        console.log('fileInfo的所有属性:', Object.keys(fileInfo));
        
        if (!fileInfo || (!fileInfo.size && !fileInfo.format)) {
            showMessage('获取文件信息失败：文件信息为空', 'error');
            return;
        }
        
        // 处理基本信息 - 适配新的数据结构
        const fileSize = fileInfo.size || 0;
        const fileSizeFormatted = formatFileSize(fileSize);
        const fileType = fileInfo.format || fileInfo.type || '未知';
        const lastModified = fileInfo.lastModified;
        
        let modifiedTimeString = '未知';
        if (lastModified) {
            try {
                modifiedTimeString = new Date(lastModified).toLocaleString('zh-CN');
            } catch (e) {
                console.warn('时间格式解析失败:', lastModified);
                modifiedTimeString = lastModified;
            }
        }
        
        const basicInfo = [
            { label: '文件名', value: fileName },
            { label: '文件路径', value: filePath },
            { label: '所属区域', value: browseType === 'results' ? '工作空间' : '数据源' },
            { label: '文件大小', value: fileSizeFormatted },
            { label: '文件类型', value: fileType },
            { label: '修改时间', value: modifiedTimeString }
        ];
        
        console.log('处理后的基本信息:', basicInfo); // 调试处理结果
        
        // 处理地理空间信息
        const geoInfo = [];
        const metadata = fileInfo.metadata;
        console.log('metadata存在:', !!metadata);
        console.log('metadata类型:', typeof metadata);
        if (metadata) {
            console.log('地理元数据:', metadata); // 调试元数据
            
            // 坐标系统
            if (metadata.srs) {
                const srsDisplay = metadata.srs.includes('WGS 84') ? 'WGS 84 (地理坐标系)' : metadata.srs;
                geoInfo.push({ label: '坐标系统', value: srsDisplay });
            }
            
            // 波段信息
            if (metadata.bandCount) {
                geoInfo.push({ 
                    label: '波段数量', 
                    value: `${metadata.bandCount} 个波段`
                });
            }
            
            // 影像尺寸
            const rasterSize = metadata.rasterSize;
            if (rasterSize && rasterSize.width && rasterSize.height) {
                geoInfo.push({ 
                    label: '影像尺寸', 
                    value: `${rasterSize.width} × ${rasterSize.height} 像素`
                });
                const totalPixels = rasterSize.width * rasterSize.height;
                geoInfo.push({ 
                    label: '总像素数', 
                    value: `${totalPixels.toLocaleString()} 像素`
                });
            }
            
            // 像素分辨率
            const pixelSize = metadata.pixelSize;
            if (pixelSize && pixelSize.x) {
                const pixelSizeX = Math.abs(pixelSize.x);
                const pixelSizeY = Math.abs(pixelSize.y);
                geoInfo.push({ 
                    label: '像素分辨率', 
                    value: `${pixelSizeX.toFixed(8)} × ${pixelSizeY.toFixed(8)} 度/像素`
                });
                
                // 转换为米（大概值）
                const meterX = pixelSizeX * 111320;
                const meterY = pixelSizeY * 111320;
                if (meterX < 1000) {
                    geoInfo.push({ 
                        label: '地面分辨率', 
                        value: `约 ${meterX.toFixed(2)} × ${meterY.toFixed(2)} 米/像素`
                    });
                } else {
                    geoInfo.push({ 
                        label: '地面分辨率', 
                        value: `约 ${(meterX/1000).toFixed(2)} × ${(meterY/1000).toFixed(2)} 千米/像素`
                    });
                }
            }
            
            // 地理边界
            const bounds = metadata.bounds;
            if (bounds && bounds.west !== undefined) {
                const widthDegrees = Math.abs((bounds.east ?? 0) - (bounds.west ?? 0));
                const heightDegrees = Math.abs((bounds.north ?? 0) - (bounds.south ?? 0));
                geoInfo.push({ 
                    label: '西经', 
                    value: `${bounds.west.toFixed(6)}°`
                });
                geoInfo.push({ 
                    label: '东经', 
                    value: `${bounds.east.toFixed(6)}°`
                });
                geoInfo.push({ 
                    label: '南纬', 
                    value: `${bounds.south.toFixed(6)}°`
                });
                geoInfo.push({ 
                    label: '北纬', 
                    value: `${bounds.north.toFixed(6)}°`
                });
                geoInfo.push({ 
                    label: '覆盖范围', 
                    value: `${widthDegrees.toFixed(4)}° × ${heightDegrees.toFixed(4)}°`
                });
            }
        }
        
        // 如果没有获取到地理信息，添加提示
        if (geoInfo.length === 0) {
            geoInfo.push({
                label: '地理信息',
                value: '该文件可能不是地理数据文件或暂无地理信息'
            });
        }
        
        showModal('文件详细信息', `
            <div class="info-list">
                ${basicInfo.map(item => `
                    <div class="info-row">
                        <span class="info-label">${item.label}</span>
                        <span class="info-value">${item.value}</span>
                    </div>
                `).join('')}
                ${geoInfo.map(item => `
                    <div class="info-row">
                        <span class="info-label">${item.label}</span>
                        <span class="info-value">${item.value}</span>
                    </div>
                `).join('')}
            </div>
        `, '<button class="btn btn-secondary" onclick="closeModal()">关闭</button>');
        
    }).catch(error => {
        console.error('获取文件详情失败:', error);
        showMessage('获取文件详情失败: ' + error.message, 'error');
    });
}



// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 选择数据源文件夹函数（用于地图切片和地形切片的文件夹路径）
function selectDatasourceFolder(inputId) {
    // 记录当前操作的输入框ID
    currentDatasourceInputId = inputId;
    
    // 区分是文件夹路径还是文件匹配模式
    const isFolderPath = inputId.includes('FolderPaths');
    
    if (isFolderPath) {
        // 文件夹路径：支持多选，只能选择文件夹
        filePickerCallback = (path, isFolder = true) => {
            if (!isFolder) {
                showMessage('文件夹路径只能选择文件夹', 'warning');
                return;
            }
            
            const currentValue = document.getElementById(inputId).value;
            let paths = currentValue ? currentValue.split(',').map(p => p.trim()) : [];
            
            // 避免重复添加
            if (!paths.includes(path)) {
                paths.push(path);
                document.getElementById(inputId).value = paths.join(', ');
            }
        };
    } else {
        // 文件匹配模式：支持多选，必须选择文件（tif或txt）
        filePickerCallback = (path, isFolder = false) => {
            if (isFolder) {
                showMessage('文件匹配模式必须选择具体的文件', 'warning');
                return;
            }
            
            // 检查文件类型
            const fileName = path.toLowerCase();
            if (!fileName.endsWith('.tif') && !fileName.endsWith('.tiff') && !fileName.endsWith('.txt')) {
                showMessage('文件匹配模式只能选择 .tif、.tiff 或 .txt 文件', 'warning');
                return;
            }
            
            const currentValue = document.getElementById(inputId).value;
            let patterns = currentValue ? currentValue.split(',').map(p => p.trim()) : [];
            
            // 避免重复添加
            if (!patterns.includes(path)) {
                patterns.push(path);
                document.getElementById(inputId).value = patterns.join(', ');
                
                // 更新智能推荐按钮状态
                if (inputId === 'mapFilePatterns') {
                    updateRecommendButtonState('map');
                    scheduleRefreshMapBandOptions();
                } else if (inputId === 'terrainFilePatterns') {
                    updateRecommendButtonState('terrain');
                }
            }
        };
    }
    
    // 检查模态框是否存在，如果不存在则创建
    let modal = document.getElementById('datasourcePickerModal');
    if (!modal) {
        createDatasourcePickerModal();
        modal = document.getElementById('datasourcePickerModal');
    }
    modal.style.display = 'block';
    loadDatasourcePickerFileList(''); // 加载数据源目录
}

// 选择工作空间文件夹函数（用于结果浏览）
function selectFolder(inputId) {
    filePickerCallback = (path) => {
        document.getElementById(inputId).value = path;
    };
    // 检查模态框是否存在，如果不存在则创建
    let modal = document.getElementById('filePickerModal');
    if (!modal) {
        createFilePickerModal();
        modal = document.getElementById('filePickerModal');
    }
    modal.style.display = 'block';
    loadPickerFileList(''); // 加载工作空间目录
}

// 选择工作空间文件夹（只允许选文件夹）
function selectWorkspaceFolder(inputId) {
    filePickerCallback = (path, isDir) => {
        if (!isDir) {
            showMessage('请选择文件夹', 'warning');
            return;
        }
        document.getElementById(inputId).value = path;
    };
    // 打开文件夹选择器（复用工作空间浏览器）
    let modal = document.getElementById('filePickerModal');
    if (!modal) {
        createFilePickerModal(true); // 只选文件夹
        modal = document.getElementById('filePickerModal');
    }
    modal.style.display = 'block';
    loadPickerFileList('');
}

// 创建数据源文件夹选择器模态框
function createDatasourcePickerModal() {
    const modalHtml = `
        <div id="datasourcePickerModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>选择数据源文件夹</h3>
                    <span class="close" onclick="closeDatasourcePickerModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <div class="file-browser">
                        <div class="breadcrumb" id="datasourcePickerBreadcrumb">
                            <span class="breadcrumb-item active">根目录</span>
                        </div>
                        <div class="file-list" id="datasourcePickerFileList">
                            <div class="loading">加载中...</div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="clearDatasourceSelection()">清空选择</button>
                    <button class="btn btn-secondary" onclick="closeDatasourcePickerModal()">取消</button>
                    <button class="btn btn-primary" onclick="closeDatasourcePickerModal()">完成选择</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

// 创建工作空间文件夹选择器模态框（只允许选文件夹）
function createFilePickerModal(onlyFolder = false) {
    const modalHtml = `
        <div id="filePickerModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>选择文件夹</h3>
                    <span class="close" onclick="closeModal()">&times;</span>
                </div>
                <div class="modal-body">
                    <div class="file-browser">
                        <div class="breadcrumb" id="pickerBreadcrumb">
                            <span class="breadcrumb-item active">根目录</span>
                        </div>
                        <div class="file-list" id="pickerFileList">
                            <div class="loading">加载中...</div>
                        </div>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeModal()">取消</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    window.onlyFolderPicker = onlyFolder;
}

// 加载文件夹选择器文件列表
async function loadPickerFileList(path = '') {
    const container = document.getElementById('pickerFileList');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const data = await terraForgeAPI.browseResults(path);
        let html = '';
        
        // 更新面包屑导航
        updatePickerBreadcrumb(path);
        
        // 目录
        if (data.directories) {
            data.directories.forEach(dir => {
                const fullPath = path ? `${path}/${dir.name}` : dir.name;
                html += `
                    <div class="file-item" onclick="loadPickerFileList('${fullPath}')">
                        ${renderIcon('folder', 'file-icon')}
                        <div class="file-info">
                            <div class="file-name">${dir.name}</div>
                            <div class="file-details">目录</div>
                        </div>
                        <div class="file-actions">
                            <button class="btn btn-primary" onclick="event.stopPropagation(); selectPickedFolder('${fullPath}')">选择</button>
                        </div>
                    </div>
                `;
            });
        }
        // 只允许选文件夹，不显示文件
        container.innerHTML = html || '<div class="message info">暂无文件夹</div>';
    } catch (error) {
        console.error('加载工作空间文件夹失败:', error);
        container.innerHTML = '<div class="message error">加载失败</div>';
    }
}

// 加载数据源选择器文件列表
async function loadDatasourcePickerFileList(path = '') {
    const container = document.getElementById('datasourcePickerFileList');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const data = await terraForgeAPI.browseDatasources(path);
        let html = '';
        
        // 更新面包屑
        updateDatasourcePickerBreadcrumb(path);
        
        // 目录
        if (data.directories && data.directories.length > 0) {
            data.directories.forEach(dir => {
                const fullPath = path ? `${path}/${dir.name}` : dir.name;
                html += `
                    <div class="file-item" onclick="loadDatasourcePickerFileList('${fullPath}')">
                        ${renderIcon('folder', 'file-icon')}
                        <div class="file-info">
                            <div class="file-name">${dir.name}</div>
                            <div class="file-details">目录</div>
                        </div>
                        <div class="file-actions">
                            <button class="btn btn-primary" onclick="event.stopPropagation(); selectPickedDatasourceFolder('${fullPath}', true)">选择</button>
                        </div>
                    </div>
                `;
            });
        }
        
        // 判断当前是否为文件夹路径选择模式
        const isFolderPathMode = currentDatasourceInputId && currentDatasourceInputId.includes('FolderPaths');
        
        // 文件（只在文件匹配模式下显示）
        if (!isFolderPathMode && data.datasources && data.datasources.length > 0) {
            data.datasources.forEach(file => {
                const fullPath = path ? `${path}/${file.name}` : file.name;
                html += `
                    <div class="file-item">
                        ${renderIcon('file', 'file-icon')}
                        <div class="file-info">
                            <div class="file-name">${file.name}</div>
                            <div class="file-details">${file.sizeFormatted || '文件'}</div>
                        </div>
                        <div class="file-actions">
                            <button class="btn btn-primary" onclick="selectPickedDatasourceFolder('${fullPath}', false)">选择</button>
                        </div>
                    </div>
                `;
            });
        }
        
        // 如果当前目录有内容，添加一个选择当前目录的选项（只在文件夹路径模式下显示）
        if (isFolderPathMode && path && data.directories?.length > 0) {
            html = `
                <div class="file-item" style="border: 2px solid #667eea; background: #f0f2ff;">
                    ${renderIcon('folderOpen', 'file-icon')}
                    <div class="file-info">
                        <div class="file-name" style="color: #667eea; font-weight: bold;">选择当前目录</div>
                        <div class="file-details">${path}</div>
                    </div>
                    <div class="file-actions">
                        <button class="btn btn-primary" onclick="selectPickedDatasourceFolder('${path}', true)">选择此目录</button>
                    </div>
                </div>
            ` + html;
        }
        
        container.innerHTML = html || '<div class="message info">此目录为空</div>';
    } catch (error) {
        console.error('加载数据源失败:', error);
        container.innerHTML = '<div class="message error">加载失败</div>';
    }
}

// 更新数据源选择器面包屑
function updateDatasourcePickerBreadcrumb(path) {
    const breadcrumb = document.getElementById('datasourcePickerBreadcrumb');
    let html = '<span class="breadcrumb-item" onclick="loadDatasourcePickerFileList(\'\')">根目录</span>';
    
    if (path) {
        const parts = path.split('/');
        let currentPath = '';
        parts.forEach(part => {
            currentPath = currentPath ? `${currentPath}/${part}` : part;
            html += ` / <span class="breadcrumb-item" onclick="loadDatasourcePickerFileList('${currentPath}')">${part}</span>`;
        });
    }
    
    breadcrumb.innerHTML = html;
}

// 更新工作空间文件夹选择器面包屑
function updatePickerBreadcrumb(path) {
    const breadcrumb = document.getElementById('pickerBreadcrumb');
    let html = '<span class="breadcrumb-item" onclick="loadPickerFileList(\'\')">根目录</span>';
    
    if (path) {
        const parts = path.split('/');
        let currentPath = '';
        parts.forEach(part => {
            currentPath = currentPath ? `${currentPath}/${part}` : part;
            html += ` / <span class="breadcrumb-item" onclick="loadPickerFileList('${currentPath}')">${part}</span>`;
        });
    }
    
    breadcrumb.innerHTML = html;
}

// 选择数据源文件夹（从选择器中选择）
function selectPickedDatasourceFolder(path, isFolder = true) {
    if (filePickerCallback) {
        filePickerCallback(path, isFolder);
        // 不要立即关闭模态框，支持多选
        // closeDatasourcePickerModal();
    }
}

// 关闭数据源选择器模态框
function closeDatasourcePickerModal() {
    const modal = document.getElementById('datasourcePickerModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 存储当前正在操作的输入框ID
let currentDatasourceInputId = null;

// 清空数据源选择
function clearDatasourceSelection() {
    if (currentDatasourceInputId) {
        const element = document.getElementById(currentDatasourceInputId);
        if (element) {
            element.value = '';
            
            // 更新智能推荐按钮状态（只有文件匹配模式需要更新）
            if (!currentDatasourceInputId.includes('FolderPaths')) {
                if (currentDatasourceInputId === 'mapFilePatterns') {
                    updateRecommendButtonState('map');
                    scheduleRefreshMapBandOptions();
                } else if (currentDatasourceInputId === 'terrainFilePatterns') {
                    updateRecommendButtonState('terrain');
                }
            }
            
            showMessage('选择已清空', 'info');
        }
    } else {
        showMessage('请先点击浏览按钮选择文件', 'warning');
    }
}

// 选择工作空间文件夹
function selectPickedFolder(path) {
    if (filePickerCallback) {
        filePickerCallback(path, true);
        closeModal();
    }
}

// 透明瓦片扫描
async function scanNodataTiles() {
    const folder = document.getElementById('nodataFolder').value;
    if (!folder) {
        showMessage('请先选择文件夹', 'warning');
        return;
    }
    try {
        const panel = document.getElementById('nodataResult');
        if (panel) panel.innerHTML = '<div class="loading">扫描中...</div>';

        const threshold = parseFloat(document.getElementById('nodataThreshold')?.value ?? '0.1');
        const includeDetails = !!document.getElementById('nodataIncludeDetails')?.checked;
        const result = await terraForgeAPI.scanNodataTiles({
            path: folder,
            transparencyThreshold: threshold,
            includeDetails
        });

        const summary = result?.summary || {};
        const sampleFiles = (result?.nodataFiles || []).slice(0, 20).map(p => `
            <div class="info-row"><span class="info-label">${escapeHtml(p)}</span><span class="info-value">nodata</span></div>
        `).join('');

        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">检查瓦片数</span><span class="info-value">${summary.totalChecked ?? 0}</span></div>
                    <div class="info-row"><span class="info-label">透明瓦片</span><span class="info-value">${summary.nodataTiles ?? 0} (${summary.nodataPercentage ?? 0}%)</span></div>
                    <div class="info-row"><span class="info-label">阈值</span><span class="info-value">${escapeHtml(String(summary.transparencyThreshold ?? threshold))}</span></div>
                </div>
                ${sampleFiles ? `<div class="info-list">${sampleFiles}</div>` : '<div class="message info">暂无明细（或未勾选返回明细）</div>'}
            `;
        }

        showMessage(result?.message || '扫描完成', 'success');
    } catch (e) {
        const panel = document.getElementById('nodataResult');
        if (panel) panel.innerHTML = `<div class="message error">扫描失败: ${escapeHtml(e.message)}</div>`;
        showMessage('扫描失败: ' + e.message, 'error');
    }
}

// 透明瓦片删除
async function deleteNodataTiles() {
    const folder = document.getElementById('nodataFolder').value;
    if (!folder) {
        showMessage('请先选择文件夹', 'warning');
        return;
    }
    try {
        const panel = document.getElementById('nodataResult');
        if (panel) panel.innerHTML = '<div class="loading">删除中...</div>';

        const threshold = parseFloat(document.getElementById('nodataThreshold')?.value ?? '0.1');
        const includeDetails = !!document.getElementById('nodataIncludeDetails')?.checked;
        const result = await terraForgeAPI.deleteNodataTiles({
            path: folder,
            transparencyThreshold: threshold,
            includeDetails
        });

        const summary = result?.summary || {};
        const deletedFiles = (result?.deleted_files || result?.deletedFiles || []).slice(0, 20).map(p => `
            <div class="info-row"><span class="info-label">${escapeHtml(p)}</span><span class="info-value">deleted</span></div>
        `).join('');

        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">检查瓦片数</span><span class="info-value">${summary.totalChecked ?? result.totalChecked ?? 0}</span></div>
                    <div class="info-row"><span class="info-label">删除数量</span><span class="info-value">${summary.deletedTiles ?? result.deleted_count ?? result.deletedTiles ?? 0}</span></div>
                    <div class="info-row"><span class="info-label">清理目录</span><span class="info-value">${summary.cleanedDirs ?? result.cleanedDirs ?? 0}</span></div>
                    <div class="info-row"><span class="info-label">阈值</span><span class="info-value">${escapeHtml(String(summary.transparency_threshold ?? summary.transparencyThreshold ?? threshold))}</span></div>
                </div>
                ${deletedFiles ? `<div class="info-list">${deletedFiles}</div>` : '<div class="message info">暂无删除明细（或未勾选返回明细）</div>'}
            `;
        }

        showMessage(result?.message || '删除完成', 'success');
    } catch (e) {
        const panel = document.getElementById('nodataResult');
        if (panel) panel.innerHTML = `<div class="message error">删除失败: ${escapeHtml(e.message)}</div>`;
        showMessage('删除失败: ' + e.message, 'error');
    }
}

// layer.json 生成
async function generateLayerJson() {
    const folder = document.getElementById('layerJsonFolder').value;
    if (!folder) {
        showMessage('请先选择文件夹', 'warning');
        return;
    }
    try {
        const panel = document.getElementById('layerJsonResult');
        if (panel) panel.innerHTML = '<div class="loading">执行中...</div>';

        const boundsRaw = document.getElementById('layerJsonBounds')?.value?.trim() || '';
        const sourceFile = document.getElementById('layerJsonSourceFile')?.value?.trim() || '';
        const threads = parseInt(document.getElementById('layerJsonThreads')?.value ?? '2', 10);
        const maxMemory = document.getElementById('layerJsonMaxMemory')?.value || '8g';

        let bounds = undefined;
        if (boundsRaw) {
            const parts = boundsRaw.split(',').map(p => p.trim()).filter(Boolean);
            if (parts.length === 4) {
                const nums = parts.map(v => parseFloat(v));
                if (nums.every(n => Number.isFinite(n))) {
                    bounds = nums;
                }
            }
        }

        const result = await terraForgeAPI.updateLayerJson({
            folderPath: folder,
            bounds,
            sourceFile: sourceFile || undefined,
            threads: Number.isFinite(threads) ? threads : 2,
            maxMemory
        });

        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">目录</span><span class="info-value">${escapeHtml(result.terrainDir || folder)}</span></div>
                    <div class="info-row"><span class="info-label">方法</span><span class="info-value">${escapeHtml(result.method || '-') }</span></div>
                    <div class="info-row"><span class="info-label">layer.json</span><span class="info-value">${escapeHtml(result.layerFile || '-') }</span></div>
                    <div class="info-row"><span class="info-label">层级</span><span class="info-value">${escapeHtml(`${result.detectedLevels?.minZoom ?? '-'} - ${result.detectedLevels?.maxZoom ?? '-'}`)}</span></div>
                </div>
            `;
        }

        showMessage(result?.message || 'layer.json 处理完成', 'success');
    } catch (e) {
        const panel = document.getElementById('layerJsonResult');
        if (panel) panel.innerHTML = `<div class="message error">执行失败: ${escapeHtml(e.message)}</div>`;
        showMessage('生成失败: ' + e.message, 'error');
    }
}

async function runTerrainDecompressTool() {
    const folder = document.getElementById('terrainDecompressFolder')?.value || '';
    if (!folder) {
        showMessage('请先选择文件夹', 'warning');
        return;
    }

    const panel = document.getElementById('terrainDecompressResult');
    if (panel) panel.innerHTML = '<div class="loading">解压中...</div>';

    try {
        const result = await terraForgeAPI.decompressTerrain({ folderPath: folder });
        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">目录</span><span class="info-value">${escapeHtml(result.terrainDir || folder)}</span></div>
                    <div class="info-row"><span class="info-label">路径</span><span class="info-value">${escapeHtml(result.terrainPath || '-')}</span></div>
                </div>
            `;
        }
        showMessage(result?.message || '解压完成', 'success');
    } catch (e) {
        if (panel) panel.innerHTML = `<div class="message error">解压失败: ${escapeHtml(e.message)}</div>`;
        showMessage('解压失败: ' + e.message, 'error');
    }
}

async function runTileConvertTool() {
    const sourcePath = document.getElementById('tileConvertSourcePath')?.value || '';
    const targetPath = document.getElementById('tileConvertTargetPath')?.value || '';
    const sourceFormat = document.getElementById('tileConvertSourceFormat')?.value || 'flat';
    const targetFormat = document.getElementById('tileConvertTargetFormat')?.value || 'nested';
    const overwrite = !!document.getElementById('tileConvertOverwrite')?.checked;
    const panel = document.getElementById('tileConvertResult');

    if (!sourcePath || !targetPath) {
        showMessage('请先选择源目录与目标目录', 'warning');
        return;
    }
    if (sourcePath === targetPath) {
        showMessage('源目录与目标目录不能相同', 'warning');
        return;
    }
    if (sourceFormat === targetFormat) {
        showMessage('源格式与目标格式不能相同', 'warning');
        return;
    }

    if (panel) panel.innerHTML = '<div class="loading">正在提交转换任务...</div>';
    try {
        const result = await terraForgeAPI.convertTileFormat({
            sourcePath,
            targetPath,
            sourceFormat,
            targetFormat,
            overwrite
        });

        if (panel) {
            panel.innerHTML = `
                <div class="info-list">
                    <div class="info-row"><span class="info-label">任务ID</span><span class="info-value">${escapeHtml(result.taskId || '')}</span></div>
                    <div class="info-row"><span class="info-label">源目录</span><span class="info-value">${escapeHtml(result.sourcePath || '')}</span></div>
                    <div class="info-row"><span class="info-label">目标目录</span><span class="info-value">${escapeHtml(result.targetPath || '')}</span></div>
                </div>
                <div class="tool-actions">
                    <button class="btn btn-secondary" onclick="switchSection('tasks')">查看任务</button>
                </div>
            `;
        }

        showMessage(result?.message || `转换任务已启动: ${result.taskId}`, 'success');
    } catch (e) {
        if (panel) panel.innerHTML = `<div class="message error">提交失败: ${escapeHtml(e.message)}</div>`;
        showMessage('提交失败: ' + e.message, 'error');
    }
}

// 更新系统状态和配置信息
async function updateSystemInfo() {
    try {
        // 显示刷新开始提示
        showRefreshIndicator(true);
        
        const [healthData, systemInfo, taskData] = await Promise.all([
            terraForgeAPI.getHealthStatus(),
            terraForgeAPI.getSystemInfo(),
            terraForgeAPI.getAllTasks()
        ]);

        console.log('系统信息数据:', systemInfo); // 调试用

        // 更新任务概览数据
        updateOverviewCards(taskData);

        // 更新系统状态
        const healthStatus = document.getElementById('healthStatus');
        if (healthStatus) {
            healthStatus.innerHTML = `
                <div class="dashboard-info-item">
                    <span class="dashboard-label">服务状态</span>
                    <span class="dashboard-value ${healthData.status === 'healthy' ? 'text-success' : 'text-danger'}">
                        ${healthData.status === 'healthy' ? '🟢 正常运行' : '🔴 服务异常'}
                    </span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">API版本</span>
                    <span class="dashboard-value">${healthData.version || '未知'}</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">最后检查</span>
                    <span class="dashboard-value">${healthData.timestamp || '未知'}</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">数据库</span>
                    <span class="dashboard-value">${healthData.database?.status || '未知'}</span>
                </div>
            `;
        }

        // 更新系统配置 - 显示更丰富的信息
        const systemConfig = document.getElementById('systemConfig');
        if (systemConfig) {
            // 提取系统信息
            const cpuCount = systemInfo?.system?.cpuCount || systemInfo?.cpuCount || '未知';
            const memoryTotal = formatMemory(systemInfo?.system?.memoryTotal || systemInfo?.memoryTotal);
            const memoryAvailable = formatMemory(systemInfo?.system?.memoryAvailable || systemInfo?.memoryAvailable);
            const diskUsage = systemInfo?.system?.diskUsage ? `${systemInfo.system.diskUsage.toFixed(1)}%` : '未知';
            
            // 提取配置信息
            const maxThreads = systemInfo?.config?.maxThreads || '未知';
            
            // 计算内存使用率
            let memoryUsage = '未知';
            if (systemInfo?.system?.memoryTotal && systemInfo?.system?.memoryAvailable) {
                const used = systemInfo.system.memoryTotal - systemInfo.system.memoryAvailable;
                const usagePercent = (used / systemInfo.system.memoryTotal * 100).toFixed(1);
                memoryUsage = `${usagePercent}%`;
            }
            
            systemConfig.innerHTML = `
                <div class="dashboard-info-item">
                    <span class="dashboard-label">CPU核心数</span>
                    <span class="dashboard-value">🖥️ ${cpuCount} 核</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">内存总量</span>
                    <span class="dashboard-value">💾 ${memoryTotal}</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">可用内存</span>
                    <span class="dashboard-value">📊 ${memoryAvailable} (${memoryUsage})</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">磁盘使用率</span>
                    <span class="dashboard-value">💿 ${diskUsage}</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">最大线程数</span>
                    <span class="dashboard-value">⚙️ ${maxThreads}</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">数据源目录</span>
                    <span class="dashboard-value">${systemInfo?.config?.dataSourceDir || '未知'}</span>
                </div>
                <div class="dashboard-info-item">
                    <span class="dashboard-label">结果目录</span>
                    <span class="dashboard-value">${systemInfo?.config?.tilesDir || '未知'}</span>
                </div>
            `;
        }
        const dataDirectory = document.getElementById('dataDirectory');
        if (dataDirectory) {
            dataDirectory.textContent = systemInfo?.config?.dataSourceDir || '未知';
        }


        
        // 显示刷新成功提示
        showRefreshIndicator(false, true);
        
    } catch (error) {
        console.error('更新系统信息失败:', error);
        showRefreshIndicator(false, false);
        showMessage('获取系统信息失败', 'error');
    }
}

// 更新任务概览卡片
function updateOverviewCards(taskData) {
    if (!taskData || !taskData.tasks) {
        return;
    }
    
    const tasks = Object.values(taskData.tasks);
    const totalTasks = tasks.length;
    const completedTasks = tasks.filter(task => task.status === 'completed').length;
    const runningTasks = tasks.filter(task => task.status === 'running').length;
    const failedTasks = tasks.filter(task => task.status === 'failed').length;
    
    // 更新卡片数据
    const cards = document.querySelectorAll('.overview-card .card-value');
    if (cards.length >= 4) {
        cards[0].textContent = totalTasks;
        cards[1].textContent = completedTasks;
        cards[2].textContent = runningTasks;
        cards[3].textContent = failedTasks;
    }
}

// 格式化内存显示
function formatMemory(bytes) {
    if (!bytes || bytes === 0) return '未知';
    
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = bytes;
    let unitIndex = 0;
    
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    
    return `${size.toFixed(1)} ${units[unitIndex]}`;
}

// 定时更新系统信息
setInterval(updateSystemInfo, 30000); // 每30秒更新一次 

// 显示刷新指示器
function showRefreshIndicator(isRefreshing, success = null) {
    const existingIndicator = document.getElementById('refreshIndicator');
    if (existingIndicator) {
        existingIndicator.remove();
    }
    
    if (isRefreshing) {
        // 显示刷新中指示器 - 使用统一的消息框样式
        const indicator = document.createElement('div');
        indicator.id = 'refreshIndicator';
        indicator.className = 'toast-message message info refresh-indicator';
        indicator.innerHTML = `
            <i class="refresh-icon">🔄</i>
            <span>正在刷新系统信息...</span>
        `;
        document.body.appendChild(indicator);
    } else if (success !== null) {
        // // 显示刷新结果 - 使用统一的消息框样式
        // const indicator = document.createElement('div');
        // indicator.id = 'refreshIndicator';
        // indicator.className = `message ${success ? 'success' : 'error'}`;
        // indicator.innerHTML = `
        //     <i class="fas ${success ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
        //     <span>${success ? '系统信息已更新' : '刷新失败'}</span>
        // `;
        // indicator.style.top = '60px'; // 避免和其他消息重叠
        // document.body.appendChild(indicator);
        //
        // // 2秒后自动消失
        // setTimeout(() => {
        //     if (indicator.parentElement) {
        //         indicator.style.animation = 'slideUp 0.3s ease-out forwards';
        //         setTimeout(() => indicator.remove(), 300);
        //     }
        // }, 2000);
    }
}

function closeModal() {
    // 关闭文件选择器模态框
    const filePickerModal = document.getElementById('filePickerModal');
    if (filePickerModal) {
        filePickerModal.style.display = 'none';
    }
    // 关闭通用模态框
    const modal = document.getElementById('modal');
    if (modal) {
        modal.style.display = 'none';
    }
    filePickerCallback = null;
}

 
