import { NavLink, Outlet } from 'react-router-dom';
import ProfileMenu from './ProfileMenu';
import { useAuth } from '../context/AuthContext';

const NAV_ITEMS = [
  { to: '/videos', label: 'Мои видео', icon: '▤' },
  { to: '/projects', label: 'Проекты', icon: '⌗' },
  { to: '/publish', label: 'Публикация', icon: '⤴' },
  { to: '/accounts', label: 'Аккаунты', icon: '◎' },
  { to: '/billing', label: 'Биллинг', icon: '◈' },
  { to: '/settings', label: 'Настройки', icon: '⚙' },
];

export default function Layout({ breadcrumb }) {
  const { user } = useAuth();
  const navItems = user?.is_admin
    ? [...NAV_ITEMS, { to: '/admin', label: 'Админка', icon: '★' }]
    : NAV_ITEMS;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="topbar">
        <div className="topbar-left">
          <div className="logo">short<span>cut</span></div>
          {breadcrumb && <div className="breadcrumb">{breadcrumb}</div>}
        </div>
        <ProfileMenu />
      </div>

      <div className="shell">
        <nav className="nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            >
              <span className="icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
