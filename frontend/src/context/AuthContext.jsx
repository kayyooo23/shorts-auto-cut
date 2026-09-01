import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    if (!api.isLoggedIn()) {
      setUser(null);
      setLoading(false);
      return null;
    }
    try {
      const me = await api.me();
      setUser(me);
      return me;
    } catch {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
    const onLogout = () => setUser(null);
    window.addEventListener('shorts:logout', onLogout);
    return () => window.removeEventListener('shorts:logout', onLogout);
  }, [loadUser]);

  const login = async (email, password, remember = true) => {
    await api.login(email, password, remember);
    return loadUser();
  };

  const register = async (email, password) => {
    await api.register(email, password);
    await login(email, password);
  };

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser: loadUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth должен использоваться внутри AuthProvider');
  return ctx;
}
