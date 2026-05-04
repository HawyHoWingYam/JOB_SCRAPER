import React from 'react';
import { LayoutDashboard, Briefcase, CalendarClock, Settings, Activity, BrainCircuit, Building2 } from 'lucide-react';
import './Sidebar.css';

const Sidebar = ({ activeView, setActiveView }) => {
    const navItems = [
        { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { id: 'jobs', label: 'Job Browser', icon: Briefcase },
        { id: 'companies', label: 'Companies', icon: Building2 },
        { id: 'ai', label: 'AI Enrichment', icon: BrainCircuit },
        { id: 'scheduler', label: 'Scheduler', icon: CalendarClock },
    ];

    return (
        <aside className="sidebar glass-panel">
            <div className="sidebar-header">
                <div className="logo-container">
                    <Activity className="logo-icon" size={28} />
                    <h1 className="logo-text">DataNexus</h1>
                </div>
                <div className="logo-subtitle">Enterprise Scraper Engine</div>
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
                >
                    <Settings size={20} className="nav-icon" />
                    <span>Settings</span>
                    {activeView === 'settings' && <div className="active-indicator" />}
                </button>
                <div className="system-status">
                    <div className="status-dot online"></div>
                    <span>System Online</span>
                </div>
            </div>
        </aside>
    );
};

export default Sidebar;
