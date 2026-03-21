import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import clsx from 'clsx';
import { LayoutDashboard, Route, ShieldAlert, Camera, Bell, CloudSun, Map, Settings, Activity, User, TrendingUp } from 'lucide-react';

interface NavItem { icon: typeof LayoutDashboard; label: string; to: string; }

const navItems: NavItem[] = [
  { icon: LayoutDashboard, label: 'Dashboard', to: '/' },
  { icon: Map, label: 'Map', to: '/map' },
  { icon: Route, label: 'Segments', to: '/segments' },
  { icon: ShieldAlert, label: 'Risk Analysis', to: '/risk' },
  { icon: TrendingUp, label: 'Predictions', to: '/predictions' },
  { icon: Camera, label: 'Cameras', to: '/cameras' },
  { icon: Bell, label: 'Alerts', to: '/alerts' },
  { icon: CloudSun, label: 'Weather', to: '/weather' },
  { icon: Settings, label: 'Settings', to: '/settings' },
];

export default function Sidebar() {
  const [expanded, setExpanded] = useState(false);
  return (
    <aside onMouseEnter={() => setExpanded(true)} onMouseLeave={() => setExpanded(false)}
      className={clsx('fixed left-0 top-0 h-screen bg-[#111820] border-r border-[#1E2A3A] z-50 flex flex-col transition-all duration-150 ease-in-out overflow-hidden', expanded ? 'w-60' : 'w-[72px]')}>
      <div className="h-16 flex items-center gap-3 px-5 border-b border-[#1E2A3A] shrink-0">
        <div className="w-8 h-8 rounded-lg bg-[#D4915E] flex items-center justify-center shrink-0">
          <Activity size={18} className="text-[#0B0F14]" />
        </div>
        <span className={clsx('text-[15px] font-semibold tracking-[-0.02em] text-[#F4F5F7] whitespace-nowrap transition-opacity duration-150', expanded ? 'opacity-100' : 'opacity-0')}>
          Traffic AI
        </span>
      </div>
      <nav className="flex-1 py-4 flex flex-col gap-1 px-3">
        {navItems.map((item) => (
          <NavLink key={item.to} to={item.to}
            className={({ isActive }) => clsx('flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] font-medium transition-all duration-150 ease-in-out relative',
              isActive ? 'text-[#D4915E] bg-[#D4915E]/8' : 'text-[#9BA3B0] hover:text-[#F4F5F7] hover:bg-[#1A2230]')}>
            {({ isActive }) => (
              <>
                {isActive && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-[#D4915E] rounded-r" />}
                <item.icon size={20} className="shrink-0" />
                <span className={clsx('whitespace-nowrap transition-opacity duration-150', expanded ? 'opacity-100' : 'opacity-0')}>{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-[#1E2A3A] flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-[#232E3F] flex items-center justify-center shrink-0">
          <User size={16} className="text-[#9BA3B0]" />
        </div>
        <span className={clsx('text-[13px] text-[#9BA3B0] whitespace-nowrap transition-opacity duration-150', expanded ? 'opacity-100' : 'opacity-0')}>Operator</span>
      </div>
    </aside>
  );
}