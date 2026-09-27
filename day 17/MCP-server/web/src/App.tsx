// Маршруты приложения в обёртке Layout.
import type { ReactNode } from 'react';
import { Link, Outlet, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout.js';
import { EmptyState } from './components/ui.js';
import { Dashboard } from './pages/Dashboard.js';
import { Providers } from './pages/Providers.js';
import { ProviderDetail } from './pages/ProviderDetail.js';
import { Logs } from './pages/Logs.js';
import { Settings } from './pages/Settings.js';

function Shell(): ReactNode {
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

function NotFound(): ReactNode {
  return (
    <div className="page">
      <EmptyState title="Page not found" description="Такой страницы не существует." />
      <div className="back-link">
        <Link to="/">← Back to Dashboard</Link>
      </div>
    </div>
  );
}

export function App(): ReactNode {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/providers/:id" element={<ProviderDetail />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}