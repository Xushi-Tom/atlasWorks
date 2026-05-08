export function formatBytes(value) {
    const size = Number(value || 0);
    if (!Number.isFinite(size) || size <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
    const scaled = size / (1024 ** index);
    return `${scaled >= 100 || index === 0 ? scaled.toFixed(0) : scaled.toFixed(1)} ${units[index]}`;
}

export function formatDateTime(value) {
    if (!value) return '-';
    const date = typeof value === 'number' ? new Date(value) : new Date(String(value));
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('zh-CN');
}

export function formatPercent(value, digits = 1) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) return '-';
    return `${num.toFixed(digits)}%`;
}

export function normalizeListInput(value) {
    return String(value || '')
        .replace(/\r/g, '\n')
        .replace(/,/g, '\n')
        .split('\n')
        .map(item => item.trim())
        .filter(Boolean);
}
