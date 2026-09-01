import { useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';

export default function AccountsPage() {
  const [platforms, setPlatforms] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState(null);

  async function load() {
    const [p, a] = await Promise.all([api.listPlatforms(), api.listSocialAccounts()]);
    setPlatforms(p);
    setAccounts(a);
  }

  useEffect(() => { load(); }, []);

  async function handleConnect(platform) {
    setError(null);
    try {
      const { authorize_url } = await api.connectSocialAccount(platform);
      window.open(authorize_url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось начать подключение');
    }
  }

  async function handleDisconnect(id) {
    await api.disconnectSocialAccount(id);
    await load();
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 20 }}>Аккаунты</h1>

      {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="platform-grid">
        {platforms.map((p) => (
          <div key={p.platform} className="platform-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>{p.platform}</span>
              {!p.enabled && <span className="tag tag-neutral">скоро</span>}
            </div>
            <button
              className="btn btn-ghost"
              disabled={!p.enabled}
              onClick={() => handleConnect(p.platform)}
              style={{ width: '100%' }}
            >
              + Подключить аккаунт
            </button>
          </div>
        ))}
      </div>

      <div className="prop-section-title" style={{ marginTop: 28, marginBottom: 12 }}>Подключённые аккаунты</div>
      {accounts.length === 0 ? (
        <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>Пока ничего не подключено</p>
      ) : (
        <div className="video-list">
          {accounts.map((a) => (
            <div key={a.id} className="video-row" style={{ cursor: 'default' }}>
              <span className="tag tag-neutral">{a.platform}</span>
              <span style={{ flex: 1, fontSize: 13 }}>{a.platform_username || a.id.slice(0, 8)}</span>
              <button className="btn btn-danger btn-sm" onClick={() => handleDisconnect(a.id)}>Отключить</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
