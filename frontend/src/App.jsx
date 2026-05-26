import React, { Suspense, lazy, useState } from 'react';
import Sidebar from './components/Sidebar';
import './App.css';

const Dashboard = lazy(() => import('./components/Dashboard'));
const JobBrowser = lazy(() => import('./components/JobBrowser'));
const AIEnrichmentPage = lazy(() => import('./components/ai/AIEnrichmentPage'));
const CompaniesPage = lazy(() => import('./components/companies/CompaniesPage'));
const AISettingsPage = lazy(() => import('./components/settings/AISettingsPage'));
const ScheduleManager = lazy(() => import('./components/scraper/ScheduleManager'));

function App() {
  const [activeView, setActiveView] = useState('dashboard');
  const navigateToAI = () => setActiveView('ai');

  return (
    <div className="app-layout">
      <Sidebar activeView={activeView} setActiveView={setActiveView} />

      <main className="app-main">
        <div className="app-content-wrapper">
          <Suspense fallback={<div className="app-view-loading">Loading view...</div>}>
            {activeView === 'dashboard' && <Dashboard onNavigateToAI={navigateToAI} />}
            {activeView === 'jobs' && <JobBrowser />}
            {activeView === 'companies' && <CompaniesPage />}
            {activeView === 'ai' && <AIEnrichmentPage />}
            {activeView === 'settings' && <AISettingsPage />}
            {activeView === 'scheduler' && <ScheduleManager onNavigateToAI={navigateToAI} />}
          </Suspense>
        </div>
      </main>
    </div>
  );
}

export default App;
