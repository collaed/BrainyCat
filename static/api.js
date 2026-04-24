/* BrainyCat shared API utilities */

const _scriptSrc = document.currentScript?.src || '';
const BASE = _scriptSrc ? new URL('..', _scriptSrc).pathname.replace(/\/$/, '') : '';
const API = BASE + '/api/v1';

async function api(path, opts = {}) {
    const headers = {...(opts.headers || {})};
    if (opts.body && typeof opts.body === 'string') headers['Content-Type'] = 'application/json';
    const resp = await fetch(API + path, {...opts, headers});
    if (!resp.ok) {
        console.error('API error:', resp.status, API + path);
        const text = await resp.text();
        try { return JSON.parse(text); } catch { return {error: text, status: resp.status}; }
    }
    if (resp.headers.get('content-type')?.includes('json')) return resp.json();
    return resp;
}

const BC = {
    base: BASE,
    get: (p) => api(p),
    post: (p, body) => api(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
    put: (p, body) => api(p, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
    patch: (p, body) => api(p, { method: 'PATCH', body: JSON.stringify(body) }),
    del: (p) => api(p, { method: 'DELETE' }),
    upload: async (p, file) => {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch(API + p, { method: 'POST', body: fd, credentials: 'same-origin' });
        return r.json();
    },
};
