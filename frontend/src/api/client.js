const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function getTokens() {
  const raw = localStorage.getItem('shorts_tokens');
  return raw ? JSON.parse(raw) : null;
}

/**
 * URL для <video src="..."> / <img src="..."> — тег не может слать
 * заголовок Authorization на свои запросы, поэтому токен передаётся
 * через query-параметр (см. backend app/auth.py::get_media_user).
 */
function mediaUrl(path) {
  const tokens = getTokens();
  const token = tokens?.access_token || '';
  return `${BASE_URL}${path}?token=${encodeURIComponent(token)}`;
}

function setTokens(tokens) {
  if (tokens) {
    localStorage.setItem('shorts_tokens', JSON.stringify(tokens));
  } else {
    localStorage.removeItem('shorts_tokens');
  }
}

class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

let refreshPromise = null;

async function refreshAccessToken() {
  const tokens = getTokens();
  if (!tokens?.refresh_token) throw new ApiError(401, 'Не авторизован');

  // Не даём нескольким параллельным 401 запустить рефреш одновременно —
  // все ждут один и тот же промис.
  if (!refreshPromise) {
    refreshPromise = fetch(`${BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refresh_token }),
    })
      .then(async (res) => {
        if (!res.ok) throw new ApiError(res.status, 'Сессия истекла');
        const data = await res.json();
        setTokens({ ...tokens, access_token: data.access_token });
        return data.access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function request(path, { method = 'GET', body, isForm = false, auth = true, _retried = false } = {}) {
  const headers = {};
  if (!isForm) headers['Content-Type'] = 'application/json';

  if (auth) {
    const tokens = getTokens();
    if (tokens?.access_token) headers['Authorization'] = `Bearer ${tokens.access_token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth && !_retried) {
    try {
      await refreshAccessToken();
      return request(path, { method, body, isForm, auth, _retried: true });
    } catch {
      setTokens(null);
      window.dispatchEvent(new Event('shorts:logout'));
      throw new ApiError(401, 'Сессия истекла, войди заново');
    }
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
    } catch {
      /* ответ без тела */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // ---------- Авторизация ----------
  async register(email, password) {
    return request('/auth/register', { method: 'POST', body: { email, password }, auth: false });
  },
  async login(email, password) {
    const data = await request('/auth/login', { method: 'POST', body: { email, password }, auth: false });
    setTokens(data);
    return data;
  },
  async logout() {
    const tokens = getTokens();
    if (tokens?.refresh_token) {
      try {
        await request('/auth/logout', { method: 'POST', body: { refresh_token: tokens.refresh_token }, auth: false });
      } catch {
        /* всё равно чистим локально */
      }
    }
    setTokens(null);
  },
  async me() {
    return request('/auth/me');
  },
  isLoggedIn() {
    return Boolean(getTokens()?.access_token);
  },
  async changePassword(currentPassword, newPassword) {
    return request('/auth/change-password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    });
  },
  async deleteAccount(currentPassword) {
    return request('/auth/me', { method: 'DELETE', body: { current_password: currentPassword } });
  },
  async forgotPassword(email) {
    return request('/auth/forgot-password', { method: 'POST', body: { email }, auth: false });
  },
  async resetPassword(token, newPassword) {
    return request('/auth/reset-password', {
      method: 'POST',
      body: { token, new_password: newPassword },
      auth: false,
    });
  },

  // ---------- Видео ----------
  async uploadVideo(file, onProgress) {
    const form = new FormData();
    form.append('file', file);
    // fetch не отдаёт прогресс аплоада нативно — используем XHR только для этого запроса
    return new Promise((resolve, reject) => {
      const tokens = getTokens();
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/videos/upload`);
      if (tokens?.access_token) xhr.setRequestHeader('Authorization', `Bearer ${tokens.access_token}`);
      xhr.upload.onprogress = (e) => {
        if (onProgress && e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) resolve(data);
          else reject(new ApiError(xhr.status, data.detail));
        } catch (e) {
          reject(e);
        }
      };
      xhr.onerror = () => reject(new ApiError(0, 'Сетевая ошибка при загрузке'));
      xhr.send(form);
    });
  },
  async listVideos() {
    return request('/videos');
  },
  async getVideo(id) {
    return request(`/videos/${id}`);
  },
  async getVideoMoments(id) {
    return request(`/videos/${id}/moments`);
  },

  // ---------- Моменты и субтитры ----------
  async updateMoment(id, patch) {
    return request(`/moments/${id}`, { method: 'PATCH', body: patch });
  },
  async deleteMoment(id) {
    return request(`/moments/${id}`, { method: 'DELETE' });
  },
  async createSubtitle(momentId, payload) {
    return request(`/moments/${momentId}/subtitles`, { method: 'POST', body: payload });
  },
  async updateSubtitle(id, patch) {
    return request(`/subtitles/${id}`, { method: 'PATCH', body: patch });
  },
  async deleteSubtitle(id) {
    return request(`/subtitles/${id}`, { method: 'DELETE' });
  },
  async uploadBanner(momentId, file) {
    const form = new FormData();
    form.append('file', file);
    return request(`/moments/${momentId}/banner`, { method: 'POST', body: form, isForm: true });
  },
  async deleteBanner(momentId) {
    return request(`/moments/${momentId}/banner`, { method: 'DELETE' });
  },

  // ---------- Многодорожечный монтаж (Track/Clip) ----------
  async createTrack(momentId, type, name) {
    return request(`/moments/${momentId}/tracks`, { method: 'POST', body: { type, name } });
  },
  async deleteTrack(trackId) {
    return request(`/tracks/${trackId}`, { method: 'DELETE' });
  },
  async uploadClip(trackId, file) {
    const form = new FormData();
    form.append('file', file);
    return request(`/tracks/${trackId}/clips`, { method: 'POST', body: form, isForm: true });
  },
  async updateClip(clipId, patch) {
    return request(`/clips/${clipId}`, { method: 'PATCH', body: patch });
  },
  async deleteClip(clipId) {
    return request(`/clips/${clipId}`, { method: 'DELETE' });
  },
  async renderMoment(id) {
    return request(`/moments/${id}/render`, { method: 'POST' });
  },

  // ---------- Платформы и публикация ----------
  async listPlatforms() {
    return request('/platforms', { auth: false });
  },
  async listSocialAccounts() {
    return request('/social-accounts');
  },
  async connectSocialAccount(platform) {
    return request(`/social-accounts/${platform}/connect`);
  },
  async disconnectSocialAccount(id) {
    return request(`/social-accounts/${id}`, { method: 'DELETE' });
  },
  async publishMoment(momentId, payload) {
    return request(`/moments/${momentId}/publish`, { method: 'POST', body: payload });
  },
  async getPublishTargets(momentId) {
    return request(`/moments/${momentId}/publish-targets`);
  },

  // ---------- Биллинг ----------
  async billingMe() {
    return request('/billing/me');
  },

  // ---------- Черновики хештегов ----------
  async listHashtagDrafts() {
    return request('/hashtag-drafts');
  },
  async createHashtagDraft(name, hashtags) {
    return request('/hashtag-drafts', { method: 'POST', body: { name, hashtags } });
  },
  async deleteHashtagDraft(id) {
    return request(`/hashtag-drafts/${id}`, { method: 'DELETE' });
  },
  async suggestHashtags(momentId) {
    return request(`/moments/${momentId}/suggest-hashtags`, { method: 'POST' });
  },

  // ---------- Проекты ----------
  async listProjects() {
    return request('/projects');
  },
  async createProject(payload) {
    return request('/projects', { method: 'POST', body: payload });
  },
  async updateProject(id, patch) {
    return request(`/projects/${id}`, { method: 'PATCH', body: patch });
  },
  async deleteProject(id) {
    return request(`/projects/${id}`, { method: 'DELETE' });
  },

  // ---------- Медиа (для живого предпросмотра в редакторе) ----------
  getVideoFileUrl(videoId) {
    return mediaUrl(`/videos/${videoId}/file`);
  },
  getBannerFileUrl(momentId) {
    return mediaUrl(`/moments/${momentId}/banner/file`);
  },
  getMomentThumbnailUrl(momentId) {
    return mediaUrl(`/moments/${momentId}/thumbnail`);
  },
  getVideoThumbnailUrl(videoId) {
    return mediaUrl(`/videos/${videoId}/thumbnail`);
  },
  getClipThumbnailUrl(clipId) {
    return mediaUrl(`/clips/${clipId}/thumbnail`);
  },
};

export { ApiError };
