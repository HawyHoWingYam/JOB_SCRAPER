import React, { Suspense, lazy, useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import { hashForView, resolveAppView } from './appRoute';
import { parseControlRoute } from './features/taskControl/shared/controlRoute';
import './App.css';

const Dashboard = lazy(() => import('./components/Dashboard'));
const JobBrowser = lazy(() => import('./components/JobBrowser'));
const AIEnrichmentPage = lazy(() => import('./components/ai/AIEnrichmentPage'));
const CompaniesPage = lazy(() => import('./components/companies/CompaniesPage'));
const AISettingsPage = lazy(() => import('./components/settings/AISettingsPage'));
const ScheduleManager = lazy(() => import('./components/scraper/ScheduleManager'));
const CrawlTasksPage = lazy(() => import('./components/scraper/CrawlTasksPage'));
const AddJobPage = lazy(() => import('./components/jobs/AddJobPage'));
const JobIntelligenceGovernancePage = lazy(
  () =>
    import(
      './components/jobIntelligence/JobIntelligenceGovernancePage'
    ),
);
const SourceCatalogsPage = lazy(
  () => import('./features/sourceCatalogs/SourceCatalogsPage'),
);
const TaskControlWizard = lazy(
  () => import('./features/taskControl/wizard/TaskControlWizard'),
);

function App() {
  const [activeView, setActiveView] = useState(() =>
    typeof window === 'undefined' ? 'dashboard' : resolveAppView(),
  );
  const [locationHash, setLocationHash] = useState(() =>
    typeof window === 'undefined' ? '#dashboard' : window.location.hash,
  );
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
      const nextView = resolveAppView();
      setLocationHash(window.location.hash);
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

    if (resolveAppView(window.location.hash) !== activeView) {
      window.location.hash = hashForView(activeView);
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
            {activeView === 'job-intelligence' && (
              <JobIntelligenceGovernancePage />
            )}
            {activeView === 'source-catalogs' && <SourceCatalogsPage />}
            {activeView === 'ai' && <AIEnrichmentPage />}
            {activeView === 'settings' && (
              <AISettingsPage
                initialSection={settingsSection}
                onOpenCrawlTasks={navigateToCrawlTasks}
              />
            )}
            {activeView === 'scheduler' && (
              parseControlRoute(locationHash).kind === 'board' ? (
                <ScheduleManager
                  onNavigateToAI={navigateToAI}
                  onNavigateToCrawlTasks={navigateToCrawlTasks}
                  onNavigateToScraperPacing={navigateToScraperPacing}
                />
              ) : <TaskControlWizard hash={locationHash} />
            )}
            {activeView === 'crawl-tasks' && <CrawlTasksPage />}
          </Suspense>
        </div>
      </main>
    </div>
  );
}

export default App;
