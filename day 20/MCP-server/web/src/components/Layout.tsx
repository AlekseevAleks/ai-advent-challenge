// Sidebar + топбар + контент. Responsive: sidebar превращается в drawer < 900px.
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { api } from '../api/client.js';
import type { ProviderRuntimeState } from '../api/types.js';
import {
  IconDashboard,
  IconGear,
  IconList,
  IconMenu,
  IconMoon,
  IconClock,
  IconPlug,
  IconSun,
  IconFlow,
  IconSparkles,
  LogoMark,
} from './icons.js';

const THEME_KEY = 'mcp-gateway-theme';
type Theme = 'dark' | 'light';

function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    /* localStorage недоступен */
  }
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

const navLinkClass = ({ isActive }: { isActive: boolean }): string => `nav-link${isActive ? ' active' : ''}`;

export function Layout({ children }: { children: ReactNode }): ReactNode {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [providers, setProviders] = useState<ProviderRuntimeState[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    let active = true;
    api
      .getProviders()
      .then((list) => {
        if (active) setProviders(list);
      })
      .catch(() => {
        if (active) setProviders([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

  return (
    <div className="app">
      {sidebarOpen ? <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} /> : null}
      <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="sidebar-brand">
          <LogoMark size={22} />
          <span className="sidebar-brand-name">MCP Gateway</span>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={navLinkClass}>
            <IconDashboard size={16} />
            <span>Dashboard</span>
          </NavLink>
          <NavLink to="/providers" end className={navLinkClass}>
            <IconPlug size={16} />
            <span>APIs</span>
          </NavLink>
          <NavLink to="/scheduled-tasks" className={navLinkClass}>
            <IconClock size={16} />
            <span>Scheduled Tasks</span>
          </NavLink>
          <NavLink to="/scheduled-tasks-tools" className={navLinkClass}>
            <IconGear size={16} />
            <span>Scheduled Task Tools</span>
          </NavLink>
          <NavLink to="/pipelines" className={navLinkClass}>
            <IconFlow size={16} />
            <span>Pipelines</span>
          </NavLink>
          <NavLink to="/pipelines-tools" className={navLinkClass}>
            <IconGear size={16} />
            <span>Pipelines Tools</span>
          </NavLink>
          <NavLink to="/settings/llm" className={navLinkClass}>
            <IconSparkles size={16} />
            <span>LLM Settings</span>
          </NavLink>
          <NavLink to="/logs" className={navLinkClass}>
            <IconList size={16} />
            <span>Logs</span>
          </NavLink>
          <NavLink to="/settings" className={navLinkClass}>
            <IconGear size={16} />
            <span>Settings</span>
          </NavLink>
        </nav>
        {providers.length > 0 ? (
          <div className="sidebar-section">
            <div className="sidebar-title">Providers</div>
            <div className="sidebar-providers">
              {providers.map((provider) => (
                <NavLink
                  key={provider.id}
                  to={`/providers/${encodeURIComponent(provider.id)}`}
                  className={navLinkClass}
                  title={provider.id}
                >
                  <span className="nav-provider-name">{provider.name}</span>
                </NavLink>
              ))}
            </div>
          </div>
        ) : null}
        <div className="sidebar-footer">
          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
            <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button type="button" className="btn-icon burger" aria-label="Open menu" onClick={() => setSidebarOpen(true)}>
            <IconMenu />
          </button>
          <span className="topbar-title">MCP Gateway</span>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}