import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';

export default function ProfileMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [billing, setBilling] = useState(null);
  const ref = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  useEffect(() => {
    if (open) {
      api.billingMe().then(setBilling).catch(() => {});
    }
  }, [open]);

  const initial = user?.email?.[0]?.toUpperCase() || '?';

  return (
    <div className="profile-menu" ref={ref}>
      <button className="profile-trigger" onClick={() => setOpen((o) => !o)} aria-label="Меню профиля">
        <span className="avatar">{initial}</span>
        <span className="chevron">▾</span>
      </button>

      {open && (
        <div className="profile-dropdown">
          {billing ? (
            <>
              <div className="pd-row">
                <span className="pd-label">Тариф</span>
                <span className="pd-tier">{billing.subscription_tier}</span>
              </div>
              <div className="pd-row">
                <span className="pd-label">Нарезок сегодня</span>
                <span className="pd-value">{billing.cuts_used_today} / {billing.cuts_daily_limit}</span>
              </div>
              <div className="pd-row">
                <span className="pd-label">Уникализаций сегодня</span>
                <span className="pd-value">{billing.uniqueize_used_today} / {billing.uniqueize_daily_limit}</span>
              </div>
              <div className="pd-row">
                <span className="pd-label">Монеты</span>
                <span className="pd-value warn">{billing.coin_balance}</span>
              </div>
            </>
          ) : (
            <div className="pd-row"><span className="pd-label">Загрузка…</span></div>
          )}

          <button className="pd-upgrade" onClick={() => { setOpen(false); navigate('/billing'); }}>
            Улучшить тариф
          </button>
          <button
            className="pd-link"
            onClick={() => { setOpen(false); navigate('/profile'); }}
          >
            Перейти в профиль
          </button>
          <button className="pd-link pd-logout" onClick={() => logout()}>
            Выйти
          </button>
        </div>
      )}
    </div>
  );
}
