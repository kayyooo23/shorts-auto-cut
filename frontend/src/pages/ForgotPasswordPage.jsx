import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [devResetUrl, setDevResetUrl] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.forgotPassword(email);
      setSent(true);
      // dev_reset_token приходит ТОЛЬКО вне продакшена (см. backend/app/email.py) —
      // на реальном проде этого поля не будет, и ссылку получит пользователь по почте.
      if (res.dev_reset_token) {
        setDevResetUrl(`/reset-password?token=${res.dev_reset_token}`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось отправить запрос');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="logo" style={{ marginBottom: 24 }}>short<span>cut</span></div>

        {sent ? (
          <>
            <h2 style={{ marginBottom: 4 }}>Проверь почту</h2>
            <p style={{ color: 'var(--text-soft)', fontSize: 13, marginBottom: 16 }}>
              Если аккаунт с таким email существует, на него отправлена ссылка для восстановления пароля.
            </p>
            {devResetUrl && (
              <div className="dev-hint">
                <div className="dev-hint-label">DEV-режим — email пока не подключён</div>
                <Link to={devResetUrl}>Перейти к сбросу пароля →</Link>
              </div>
            )}
            <p style={{ marginTop: 16, fontSize: 13, textAlign: 'center' }}>
              <Link to="/login">← Вернуться ко входу</Link>
            </p>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <h2 style={{ marginBottom: 4 }}>Восстановление пароля</h2>
            <p style={{ color: 'var(--text-soft)', fontSize: 13, marginBottom: 20 }}>
              Укажи email — пришлём ссылку для сброса пароля
            </p>

            <label className="field-label">Email</label>
            <input
              type="email" required value={email} placeholder="you@example.com"
              onChange={(e) => setEmail(e.target.value)}
            />

            {error && <div className="form-error">{error}</div>}

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: 20, width: '100%' }}>
              {loading ? 'Отправляем…' : 'Отправить ссылку'}
            </button>

            <p style={{ marginTop: 16, fontSize: 13, textAlign: 'center' }}>
              <Link to="/login">← Вернуться ко входу</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
