import React from 'react';
import { LayoutDashboard, Briefcase, PlusCircle, CalendarClock, Settings, DatabaseZap, BrainCircuit, Building2, ListTree } from 'lucide-react';
import './Sidebar.css';

const Sidebar = ({ activeView, setActiveView }) => {
    const navItems = [
        { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { id: 'jobs', label: 'Job Browser', icon: Briefcase },
        { id: 'add-job', label: 'Add Job', icon: PlusCircle },
        { id: 'companies', label: 'Companies', icon: Building2 },
        { id: 'ai', label: 'AI Enrichment', icon: BrainCircuit },
        { id: 'scheduler', label: 'Scheduler', icon: CalendarClock },
        { id: 'crawl-tasks', label: 'Crawl Tasks', icon: ListTree },
    ];

    return (
        <aside className="sidebar glass-panel">
            <div className="sidebar-header">
                <div className="logo-container">
                    <DatabaseZap className="logo-icon" size={26} />
                    <h1 className="logo-text">JobsDB Ops</h1>
                </div>
                <div className="logo-subtitle">Crawler operations console</div>
            </div>

            <nav className="sidebar-nav">
                {navItems.map((item) => {
                    const Icon = item.icon;
                    const isActive = activeView === item.id;
                    return (
                        <button
                            key={item.id}
                            className={`nav-item ${isActive ? 'active' : ''}`}
                            onClick={() => setActiveView(item.id)}
                            aria-label={item.label}
                        >
                            <Icon size={20} className="nav-icon" />
                            <span>{item.label}</span>
                            {isActive && <div className="active-indicator" />}
                        </button>
                    );
                })}
            </nav>

            <div className="sidebar-footer">
                <button
                    className={`nav-item ${activeView === 'settings' ? 'active' : ''}`}
                    onClick={() => setActiveView('settings')}
                    aria-label="Settings"
                >
                    <Settings size={20} className="nav-icon" />
                    <span>Settings</span>
                    {activeView === 'settings' && <div className="active-indicator" />}
                </button>
                <div className="system-status">
                    <div className="status-dot" aria-hidden="true"></div>
                    <span>Console Ready</span>
                </div>
            </div>
        </aside>
    );
};

export default Sidebar;
