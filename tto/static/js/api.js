// HTTP client for the dashboard API.
import { settings } from './format.js';

export const session = { user: null, display: null, onUnauthorized: null };

async function request(method, path, body, query) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set('lang', settings.lang);
  if (query) {
    for (const k of Object.keys(query)) {
      if (query[k] !== undefined && query[k] !== null) url.searchParams.set(k, query[k]);
    }
  }
  const headers = {};
  if (session.user) headers['X-TTO-User'] = encodeURIComponent(session.user);
  const init = { method, headers };
  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    const err = new Error('Sunucuya ulaşılamıyor');
    err.network = true;
    throw err;
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const err = new Error((data && data.error) || ('HTTP ' + res.status));
    err.status = res.status;
    if (res.status === 401 && session.onUnauthorized) session.onUnauthorized();
    throw err;
  }
  return data;
}

export const api = {
  get: (path, query) => request('GET', path, null, query),
  post: (path, body, query) => request('POST', path, body === undefined ? {} : body, query),
  del: (path, body) => request('DELETE', path, body),
};
