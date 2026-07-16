import React, { Suspense, lazy, useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import './App.css';

const Dashboard = lazy(() => import('./components/Dashboard'));
const JobBrowser = lazy(() => import('./components/JobBrowser'));
const AIEnrichmentPage = lazy(() => import('./components/ai/AIEnrichmentPage'));
const CompaniesPage = lazy(() => import('./components/companies/CompaniesPage'));
const AISettingsPage = lazy(() => import('./components/settings/AISettingsPage'));
const ScheduleManager = lazy(() => import('./components/scraper/ScheduleManager'));
const CrawlTasksPage = lazy(() => import('./components/scraper/CrawlTasksPage'));
const AddJobPage = lazy(() => import('./components/jobs/AddJobPage'));
const VALID_VIEWS = new Set(['dashboard', 'jobs', 'add-job', 'companies', 'ai', 'settings', 'scheduler', 'crawl-tasks']);

function resolveInitialView() {
  if (typeof window === 'undefined') {
    return 'dashboard';
  }

  const normalizedHash = window.location.hash.replace(/^#/, '').trim().toLowerCase();
  return VALID_VIEWS.has(normalizedHash) ? normalizedHash : 'dashboard';
}

function App() {
  const [activeView, setActiveView] = useState(resolveInitialView);
  const [settingsSection, setSettingsSection] = useState('ai-runtime');
  const navigateToAI = () => setActiveView('ai');
  const navigateToCrawlTasks = () => setActiveView('crawl-tasks');
  const navigateToScraperPacing = () => {
    setSettingsSection('scraper-pacing');
    setActiveView('settings');
  };

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }

    const handleHashChange = () => {
      const nextView = resolveInitialView();
      setActiveView((currentView) => (currentView === nextView ? currentView : nextView));
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => {
      window.removeEventListener('hashchange', handleHashChange);
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const nextHash = `#${activeView}`;
    if (window.location.hash !== nextHash) {
      window.location.hash = nextHash;
    }
  }, [activeView]);

  return (
    <div className="app-layout">
      <Sidebar activeView={activeView} setActiveView={setActiveView} />

      <main className="app-main">
        <div className="app-content-wrapper">
          <Suspense fallback={<div className="app-view-loading">Loading view...</div>}>
            {activeView === 'dashboard' && <Dashboard onNavigateToAI={navigateToAI} />}
            {activeView === 'jobs' && <JobBrowser />}
            {activeView === 'add-job' && <AddJobPage />}
            {activeView === 'companies' && <CompaniesPage />}
            {activeView === 'ai' && <AIEnrichmentPage />}
            {activeView === 'settings' && (
              <AISettingsPage
                initialSection={settingsSection}
                onOpenCrawlTasks={navigateToCrawlTasks}
              />
            )}
            {activeView === 'scheduler' && (
              <ScheduleManager
                onNavigateToAI={navigateToAI}
                onNavigateToCrawlTasks={navigateToCrawlTasks}
                onNavigateToScraperPacing={navigateToScraperPacing}
              />
            )}
            {activeView === 'crawl-tasks' && <CrawlTasksPage />}
          </Suspense>
        </div>
      </main>
    </div>
  );
}

export default App;
