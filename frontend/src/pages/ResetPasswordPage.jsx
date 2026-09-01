import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const navigate = useNavigate();

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError('Пароль должен быть не короче 8 символов');
      return;
    }
    if (password !== confirmPassword) {
      setError('Пароли не совпадают');
      return;
    }

    setLoading(true);
    try {
      await api.resetPassword(token, password);
      setDone(true);
      setTimeout(() => navigate('/login'), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сбросить пароль');
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="logo" style={{ marginBottom: 24 }}>short<span>cut</span></div>
          <div className="form-error">Ссылка неполная — не найден токен восстановления.</div>
          <p style={{ marginTop: 16, fontSize: 13, textAlign: 'center' }}>
            <Link to="/forgot-password">Запросить ссылку заново</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="logo" style={{ marginBottom: 24 }}>short<span>cut</span></div>

        {done ? (
          <>
            <h2 style={{ marginBottom: 4 }}>Пароль изменён</h2>
            <p style={{ color: 'var(--text-soft)', fontSize: 13 }}>
              Сейчас перенаправим тебя на страницу входа…
            </p>
          </>
        ) : (
          <form onSubmit={handleSubmit}>
            <h2 style={{ marginBottom: 4 }}>Новый пароль</h2>
            <p style={{ color: 'var(--text-soft)', fontSize: 13, marginBottom: 20 }}>
              Придумай новый пароль для входа
            </p>

            <label className="field-label">Новый пароль</label>
            <input
              type="password" required value={password} placeholder="Минимум 8 символов"
              onChange={(e) => setPassword(e.target.value)}
            />

            <label className="field-label" style={{ marginTop: 12 }}>Повтори пароль</label>
            <input
              type="password" required value={confirmPassword} placeholder="Ещё раз"
              onChange={(e) => setConfirmPassword(e.target.value)}
            />

            {error && <div className="form-error">{error}</div>}

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: 20, width: '100%' }}>
              {loading ? 'Сохраняем…' : 'Сохранить новый пароль'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
