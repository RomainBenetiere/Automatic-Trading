import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Bitcoin, Clock, Settings, Activity, TrendingUp, Sliders } from 'lucide-react'
import './Sidebar.css'

const NAV_ITEMS = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/crypto', label: 'Crypto Execution', icon: Bitcoin },
  { path: '/optimizer', label: 'Paramètres Optimisés', icon: Sliders },
  { path: '/history', label: 'History', icon: Clock },
  { path: '/settings', label: 'Settings', icon: Settings },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          <TrendingUp size={24} />
        </div>
        <div className="sidebar-brand-text">
          <span className="sidebar-brand-name">TradeInsight</span>
          <span className="sidebar-brand-sub">Analysis Engine</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            end={path === '/'}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`
            }
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-status">
          <Activity size={14} />
          <span>System Active</span>
        </div>
      </div>
    </aside>
  )
}
