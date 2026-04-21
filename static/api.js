/* BrainyCat shared API utilities */

// Auto-detect base path: go up from /static/api.js to the app root
const _scriptSrc = document.currentScript?.src || '';
const BASE = _scriptSrc ? new URL('..', _scriptSrc).pathname.replace(/\/$/, '') : '';
const API = BASE + '/api/v1';

async function api(path, opts = {}) {
    const resp = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    if (resp.headers.get('content-type')?.includes('json')) return resp.json();
    return resp;
}

const BC = {
    base: BASE,
    get: (p) => api(p),
    post: (p, body) => api(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
    patch: (p, body) => api(p, { method: 'PATCH', body: JSON.stringify(body) }),
    del: (p) => api(p, { method: 'DELETE' }),
    upload: async (p, file) => {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch(API + p, { method: 'POST', body: fd });
        return r.json();
    },
};
