import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../api/client';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const loggedInUser = await login(email, password);
      navigate(loggedInUser?.is_admin ? '/admin' : '/videos');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось войти');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="logo" style={{ marginBottom: 24 }}>short<span>cut</span></div>
        <h2 style={{ marginBottom: 4 }}>Вход</h2>
        <p style={{ color: 'var(--text-soft)', fontSize: 13, marginBottom: 20 }}>
          Рады видеть снова
        </p>

        <label className="field-label">Email</label>
        <input
          type="email" required value={email} placeholder="you@example.com"
          onChange={(e) => setEmail(e.target.value)}
        />

        <label className="field-label" style={{ marginTop: 12 }}>Пароль</label>
        <input
          type="password" required value={password} placeholder="••••••••"
          onChange={(e) => setPassword(e.target.value)}
        />

        {error && <div className="form-error">{error}</div>}

        <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: 20, width: '100%' }}>
          {loading ? 'Входим…' : 'Войти'}
        </button>

        <p style={{ marginTop: 12, fontSize: 13, textAlign: 'center' }}>
          <Link to="/forgot-password">Забыли пароль?</Link>
        </p>

        <p style={{ marginTop: 16, fontSize: 13, color: 'var(--text-soft)', textAlign: 'center' }}>
          Нет аккаунта? <Link to="/register">Зарегистрироваться</Link>
        </p>
      </form>
    </div>
  );
}
