/* ── Token management ───────────────────────────────────── */
const TOKEN_KEY = 'use_dev_token';

async function ensureToken() {
  let token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    try {
      const res = await fetch('/api/v1/auth/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: 'dev-reviewer', scopes: ['read', 'write', 'review'] }),
      });
      if (res.ok) {
        const data = await res.json();
        token = data.access_token;
        localStorage.setItem(TOKEN_KEY, token);
      }
    } catch (_) { /* dev token unavailable */ }
  }
  return token;
}

/* ── Core API helpers ───────────────────────────────────── */
async function apiGet(path) {
  const token = await ensureToken();
  const headers = { 'Accept': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(path, { headers });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status} ${res.statusText}`);
  return res.json();
}

async function apiPost(path, body) {
  const token = await ensureToken();
  const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body ?? {}) });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status} ${res.statusText}`);
  return res.json();
}

/* ── UI helpers ─────────────────────────────────────────── */
function badge(status) {
  const map = {
    pending: 'badge-pending',
    approved: 'badge-approved',
    rejected: 'badge-rejected',
    anomaly:  'badge-anomaly',
    dict:     'badge-dict',
    graph:    'badge-graph',
    gap:      'badge-gap',
    confirmed:   'badge-confirmed',
    unconfirmed: 'badge-unconfirmed',
    low:    'badge-low',
    medium: 'badge-medium',
    high:   'badge-high',
  };
  const cls = map[status] ?? 'badge-pending';
  return `<span class="badge ${cls}">${status}</span>`;
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch (_) { return iso; }
}

function showError(container, msg) {
  const div = document.createElement('div');
  div.className = 'error-msg';
  div.textContent = msg;
  container.prepend(div);
}

function clearErrors(container) {
  container.querySelectorAll('.error-msg').forEach(el => el.remove());
}
