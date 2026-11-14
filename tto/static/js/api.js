// HTTP client for the dashboard API.
import { settings } from './format.js';

// Who is signed in is the server's to say: the session lives in an HttpOnly cookie the browser sends by itself.
export const session = { user: null, display: null, role: null, onUnauthorized: null };

async function request(method, path, body, query) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set('lang', settings.lang);
  if (query) {
    for (const k of Object.keys(query)) {
      if (query[k] !== undefined && query[k] !== null) url.searchParams.set(k, query[k]);
    }
  }
  const headers = {};
  const init = { method, headers, credentials: 'same-origin' };
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
    // the session ended (signed out elsewhere, expired, account closed): back to the sign-in screen
    if (res.status === 401 && data && data.login && session.user && session.onUnauthorized) session.onUnauthorized();
    throw err;
  }
  return data;
}

/** Fetch a file from the API and hand it to the browser as a download (the name comes from the server). */
async function download(path, query, fallbackName) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set('lang', settings.lang);
  for (const k of Object.keys(query || {})) {
    if (query[k] !== undefined && query[k] !== null) url.searchParams.set(k, query[k]);
  }
  let res;
  try {
    res = await fetch(url, { credentials: 'same-origin' });
  } catch (e) {
    const err = new Error('Sunucuya ulaşılamıyor');
    err.network = true;
    throw err;
  }
  if (!res.ok) {
    let message = 'HTTP ' + res.status;
    try { message = (await res.json()).error || message; } catch (e) { /* not JSON */ }
    throw new Error(message);
  }
  const m = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') || '');
  const name = m ? m[1] : (fallbackName || 'indir');
  const blob = await res.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  return { name, size: blob.size };
}

export const api = {
  download,
  get: (path, query) => request('GET', path, null, query),
  post: (path, body, query) => request('POST', path, body === undefined ? {} : body, query),
  del: (path, body) => request('DELETE', path, body),
};
