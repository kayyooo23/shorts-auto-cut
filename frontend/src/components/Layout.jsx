import { NavLink, Outlet } from 'react-router-dom';
import ProfileMenu from './ProfileMenu';

const NAV_ITEMS = [
  { to: '/videos', label: 'Мои видео', icon: '▤' },
  { to: '/projects', label: 'Проекты', icon: '⌗' },
  { to: '/publish', label: 'Публикация', icon: '⤴' },
  { to: '/accounts', label: 'Аккаунты', icon: '◎' },
  { to: '/billing', label: 'Биллинг', icon: '◈' },
  { to: '/settings', label: 'Настройки', icon: '⚙' },
];

export default function Layout({ breadcrumb }) {
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
          {NAV_ITEMS.map((item) => (
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
