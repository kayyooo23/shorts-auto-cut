import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import VideosPage from './pages/VideosPage';
import ProjectsPage from './pages/ProjectsPage';
import EditorPage from './pages/EditorPage';
import AccountsPage from './pages/AccountsPage';
import BillingPage from './pages/BillingPage';
import ProfilePage from './pages/ProfilePage';
import SettingsPage from './pages/SettingsPage';
import AdminPage from './pages/AdminPage';

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ padding: 32, color: 'var(--text-soft)' }}>Загружаем…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function RequireAdmin({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ padding: 32, color: 'var(--text-soft)' }}>Загружаем…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.is_admin) return <Navigate to="/videos" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />

          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/videos" element={<VideosPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/videos/:videoId" element={<EditorPage />} />
            <Route path="/publish" element={<AccountsPage />} />
            <Route path="/accounts" element={<AccountsPage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route
              path="/admin"
              element={
                <RequireAdmin>
                  <AdminPage />
                </RequireAdmin>
              }
            />
          </Route>

          <Route path="*" element={<Navigate to="/videos" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
