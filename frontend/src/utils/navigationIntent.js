const NAVIGATION_INTENT_KEY = 'atlasworks-navigation-intent';
const NAVIGATION_EVENT_NAME = 'atlasworks:navigation-intent';

function getStorage() {
    if (typeof window === 'undefined') return null;
    return window.sessionStorage;
}

export function setNavigationIntent(intent = {}) {
    const storage = getStorage();
    if (!storage) return;
    if (!intent || !intent.section) {
        storage.removeItem(NAVIGATION_INTENT_KEY);
        return;
    }
    storage.setItem(NAVIGATION_INTENT_KEY, JSON.stringify({
        ...intent,
        timestamp: Date.now()
    }));
}

export function consumeNavigationIntent(section = '') {
    const storage = getStorage();
    if (!storage) return null;
    const raw = storage.getItem(NAVIGATION_INTENT_KEY);
    if (!raw) return null;
    try {
        const payload = JSON.parse(raw);
        if (section && payload?.section !== section) {
            return null;
        }
        storage.removeItem(NAVIGATION_INTENT_KEY);
        return payload;
    } catch {
        storage.removeItem(NAVIGATION_INTENT_KEY);
        return null;
    }
}

export function emitNavigationIntent(intent = {}) {
    if (typeof window === 'undefined' || !intent?.section) return;
    window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent(NAVIGATION_EVENT_NAME, {
            detail: intent
        }));
    }, 0);
}

export function addNavigationIntentListener(handler) {
    if (typeof window === 'undefined' || typeof handler !== 'function') return () => {};
    const listener = event => {
        handler(event?.detail || null);
    };
    window.addEventListener(NAVIGATION_EVENT_NAME, listener);
    return () => window.removeEventListener(NAVIGATION_EVENT_NAME, listener);
}
