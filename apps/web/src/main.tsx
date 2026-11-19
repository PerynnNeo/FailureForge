import React, { lazy, Suspense, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import LandingPage from './LandingPage';

const App = lazy(() => import('./App'));
const readRoute = () => window.location.hash.slice(1) || '/';

function SiteRouter() {
  const [route, setRoute] = useState(readRoute);
  const inWorkspace = /^\/(?:workspace|campaigns(?:\/[^/]+)?|cases(?:\/[^/]+)?|runtime)\/?$/.test(route);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(readRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    document.title = inWorkspace
      ? 'FailureForge · Investigation workspace'
      : 'FailureForge — Find where robots fail.';
  }, [inWorkspace]);

  return inWorkspace
    ? <Suspense fallback={<div role="status" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#f3f5f7', color: '#253746', fontFamily: 'system-ui, sans-serif' }}>Opening your workspace…</div>}><App /></Suspense>
    : <LandingPage />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><SiteRouter /></React.StrictMode>,
);
