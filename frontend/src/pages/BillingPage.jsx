import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function BillingPage() {
  const [billing, setBilling] = useState(null);

  useEffect(() => { api.billingMe().then(setBilling); }, []);

  if (!billing) return <p style={{ color: 'var(--text-soft)' }}>Загружаем…</p>;

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 20 }}>Биллинг</h1>

      <div className="metric-grid">
        <div className="metric-card">
          <div className="metric-label">Тариф</div>
          <div className="metric-value">{billing.subscription_tier}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Нарезок сегодня</div>
          <div className="metric-value mono">{billing.cuts_used_today} / {billing.cuts_daily_limit}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Уникализаций сегодня</div>
          <div className="metric-value mono">{billing.uniqueize_used_today} / {billing.uniqueize_daily_limit}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Монеты</div>
          <div className="metric-value mono" style={{ color: 'var(--warning)' }}>{billing.coin_balance}</div>
        </div>
      </div>

      <div className="prop-section-title" style={{ marginTop: 28, marginBottom: 12 }}>Аккаунты по платформам</div>
      <div className="video-list">
        {billing.platform_usage.map((p) => (
          <div key={p.platform} className="video-row" style={{ cursor: 'default' }}>
            <span className="tag tag-neutral" style={{ textTransform: 'capitalize' }}>{p.platform}</span>
            <span className="mono" style={{ flex: 1 }}>{p.connected} / {p.limit}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
