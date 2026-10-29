/**
 * Nexora API Client — Adapted for /api/v1/* endpoints
 * Based on Odysseus api.js with Nexora-specific endpoints
 *
 * Base URL resolution order:
 *   1. `?api=` query parameter            (?api=http://localhost:8000/api/v1)
 *   2. `window.NEXORA_API_BASE`
 *   3. same-origin `/api/v1`
 *
 * `setBaseUrl()` lets the app repoint the client at the backend port when the
 * UI is served by a separate static server (the default `python -m http.server`
 * dev setup on :3000).
 */

function resolveBaseUrl() {
  try {
    const fromQuery = new URLSearchParams(window.location.search).get('api');
    if (fromQuery) {
      // Security: only honour same-origin overrides to prevent a crafted link
      // from redirecting all API calls (including approvals) to an attacker-
      // controlled server.  Cross-origin values are silently ignored.
      // For cross-origin dev setups use window.NEXORA_API_BASE or the
      // dev proxy (scripts/dev_server.py) instead.
      try {
        const u = new URL(fromQuery, window.location.href);
        if (u.origin === window.location.origin) {
          return u.pathname.replace(/\/+$/, '') || '/api/v1';
        }
      } catch {
        /* malformed URL — ignore */
      }
    }
  } catch {
    /* no search params available */
  }
  if (window.NEXORA_API_BASE) return String(window.NEXORA_API_BASE).replace(/\/+$/, '');
  return '/api/v1';
}

class ApiClient {
  constructor(baseUrl = resolveBaseUrl()) {
    this.baseUrl = baseUrl;
    this.defaultHeaders = {
      'Content-Type': 'application/json',
    };
  }

  /** Repoint every typed helper at a new base (used by the boot-time probe). */
  setBaseUrl(baseUrl) {
    this.baseUrl = String(baseUrl || '').replace(/\/+$/, '') || '/api/v1';
    return this.baseUrl;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = { ...this.defaultHeaders, ...options.headers };
    let body = options.body;

    if (typeof FormData !== 'undefined' && body instanceof FormData) {
      delete headers['Content-Type'];
    } else if (body && typeof body === 'object') {
      body = JSON.stringify(body);
    }

    const config = {
      ...options,
      headers,
      body,
    };

    try {
      const response = await fetch(url, config);
      
      const contentType = response.headers.get('content-type');
      let data;
      if (contentType && contentType.includes('application/json')) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      if (!response.ok) {
        throw this.normalizeError(response, data);
      }

      return data;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      // A TypeError out of fetch() means either the connection was refused or
      // the browser refused to expose the response. The second case is the
      // misleading one: an unhandled server-side exception produces a 500 with
      // no Access-Control-Allow-Origin header (FastAPI's CORSMiddleware sits
      // inside ServerErrorMiddleware), so the browser reports the opaque
      // failure as a plain network error even though the backend did reply.
      const detail = error && error.message ? error.message : String(error);
      throw new ApiError(
        `Cannot reach the Nexora API at ${this.baseUrl}. If the backend is up, ` +
        'this is a cross-origin rejection — check the backend log for a traceback.',
        0,
        'NETWORK_ERROR',
        detail
      );
    }
  }

  normalizeError(response, data) {
    let message = 'Request failed';
    let code = 'UNKNOWN_ERROR';
    let details = null;

    if (typeof data === 'object' && data !== null) {
      if (Array.isArray(data.detail)) {
        // FastAPI / Pydantic 422 validation error: array of { loc, msg, type }
        message = data.detail.map((err) => {
          const field = Array.isArray(err.loc) ? err.loc.filter(l => l !== 'body').join('.') : '';
          return field ? `${field}: ${err.msg}` : (err.msg || JSON.stringify(err));
        }).join('; ');
      } else if (typeof data.detail === 'string') {
        message = data.detail;
      } else if (data.message && typeof data.message === 'string') {
        message = data.message;
      } else if (typeof data.detail === 'object' && data.detail !== null) {
        message = JSON.stringify(data.detail);
      }
      code = data.code || code;
      details = data.details || null;
    } else if (typeof data === 'string') {
      message = data;
    }

    return new ApiError(message, response.status, code, details);
  }

  // Convenience methods
  get(endpoint, params = {}) {
    const queryString = new URLSearchParams(params).toString();
    const url = queryString ? `${endpoint}?${queryString}` : endpoint;
    return this.request(url, { method: 'GET' });
  }

  post(endpoint, body) {
    return this.request(endpoint, { method: 'POST', body });
  }

  patch(endpoint, body) {
    return this.request(endpoint, { method: 'PATCH', body });
  }

  delete(endpoint) {
    return this.request(endpoint, { method: 'DELETE' });
  }
}

class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Singleton instance
const api = new ApiClient();

// Export for use in other modules
window.NexoraApi = api;
window.ApiError = ApiError;
window.ApiClient = ApiClient;

// ============================================================
// Typed API Methods — Mapped to Nexora Backend Endpoints
// ============================================================

// Workspaces
api.workspaces = {
  list: (params = {}) => api.get('/workspaces', params),
  get: (id) => api.get(`/workspaces/${id}`),
  create: (data) => api.post('/workspaces', data),
  update: (id, data) => api.patch(`/workspaces/${id}`, data),
  delete: (id) => api.delete(`/workspaces/${id}`),
  files: (id) => api.get(`/workspaces/${id}/files`),
  fileContent: (id, path) => api.get(`/workspaces/${id}/files/content`, { path }),
  uploadFiles: (id, fileList) => {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }
    return api.request(`/workspaces/${id}/upload`, {
      method: 'POST',
      body: formData,
    });
  },
};

// Budget Profiles
api.budgetProfiles = {
  list: () => api.get('/budget-profiles'),
  get: (id) => api.get(`/budget-profiles/${id}`),
  create: (data) => api.post('/budget-profiles', data),
  update: (id, data) => api.patch(`/budget-profiles/${id}`, data),
};

// Models
api.models = {
  list: (enabledOnly = true) => api.get('/models', { enabled_only: enabledOnly }),
  get: (id) => api.get(`/models/${id}`),
  create: (data) => api.post('/models', data),
  update: (id, data) => api.patch(`/models/${id}`, data),
};

// Standalone packages/* layer (contracts, model_router, nebius_adapter)
api.packages = {
  routing: () => api.get('/packages/routing'),
  complete: (data) => api.post('/packages/complete', data),
};

// Runs (Nexora's equivalent of sessions)
api.runs = {
  list: (params = {}) => api.get('/runs', params),
  get: (id) => api.get(`/runs/${id}`),
  create: (data) => api.post('/runs', data),
  update: (id, data) => api.patch(`/runs/${id}`, data),
  start: (id) => api.post(`/runs/${id}/start`),
  approve: (id, approvalId, approve) => api.post(`/runs/${id}/approve`, { approval_id: approvalId, approve }),
  cancel: (id) => api.post(`/runs/${id}/cancel`),
  stream: async function*(id, signal) {
    const url = `${api.baseUrl}/runs/${id}/stream`;
    const response = await fetch(url, { signal });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Stream error ${response.status}: ${text}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) {
        if (!block.trim()) continue;
        let event = 'message';
        let dataStr = '';
        for (const line of block.split('\n')) {
          if (line.startsWith('event: ')) event = line.slice(7).trim();
          else if (line.startsWith('data: ')) dataStr = line.slice(6).trim();
        }
        if (dataStr) {
          try {
            yield { event, data: JSON.parse(dataStr) };
          } catch {
            yield { event, data: dataStr };
          }
        }
      }
    }
  },
};

// Policy Decisions
api.policyDecisions = {
  list: (runId) => api.get(`/runs/${runId}/policy-decisions`),
  get: (id) => api.get(`/policy-decisions/${id}`),
};

// Tool Requests
api.toolRequests = {
  list: (runId) => api.get(`/runs/${runId}/tool-requests`),
  get: (id) => api.get(`/tool-requests/${id}`),
};

// Tool Executions
api.toolExecutions = {
  list: (runId) => api.get(`/runs/${runId}/tool-executions`),
  get: (id) => api.get(`/tool-executions/${id}`),
};

// Approvals
api.approvals = {
  list: (runId) => api.get(`/runs/${runId}/approvals`),
  get: (id) => api.get(`/approvals/${id}`),
  decide: (id, approve) => api.post(`/approvals/${id}/decide`, { approve }),
};

// Audit Events
api.auditEvents = {
  list: (runId) => api.get(`/runs/${runId}/audit-events`),
};

// Context
api.context = {
  get: (runId) => api.get(`/runs/${runId}/context`),
  compact: (runId) => api.post(`/runs/${runId}/compact`),
};

// Health
api.health = () => api.get('/health');

// Legacy session compatibility (maps to runs)
api.sessions = {
  list: (params = {}) => api.get('/runs', params),
  get: (id) => api.get(`/runs/${id}`),
  create: (data) => api.post('/runs', data),
  update: (id, data) => api.patch(`/runs/${id}`, data),
};

export { api, ApiError, ApiClient };