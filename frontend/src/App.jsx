import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import Dashboard from './components/Dashboard';
import JobBrowser from './components/JobBrowser';
import AIEnrichmentPage from './components/ai/AIEnrichmentPage';
import CompaniesPage from './components/companies/CompaniesPage';
import ScheduleManager from './components/scraper/ScheduleManager';
import './App.css';

function App() {
  const [activeView, setActiveView] = useState('dashboard');
  const navigateToAI = () => setActiveView('ai');

  return (
    <div className="app-layout">
      <Sidebar activeView={activeView} setActiveView={setActiveView} />

      <main className="app-main">
        <div className="app-content-wrapper">
          {activeView === 'dashboard' && <Dashboard onNavigateToAI={navigateToAI} />}
          {activeView === 'jobs' && <JobBrowser />}
          {activeView === 'companies' && <CompaniesPage />}
          {activeView === 'ai' && <AIEnrichmentPage />}
          {activeView === 'scheduler' && <ScheduleManager onNavigateToAI={navigateToAI} />}
        </div>
      </main>
    </div>
  );
}

export default App;
