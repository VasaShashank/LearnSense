import React from 'react';
import type { Subject } from '../../api/client';
import type { Persona } from '../common/LoginPersonaModal';
import {
  Compass,
  BookOpen,
  Map,
  Search,
  Command,
  Upload,
  Sparkles,
  Orbit,
  Building2,
  ChevronDown,
  Users,
  BarChart3,
} from 'lucide-react';

export type AppView =
  | 'DASHBOARD'    // Student home
  | 'ATLAS'        // Shared concept graph
  | 'PATH'         // Student learning path
  | 'SOURCES'      // Shared source library
  | 'MARKETPLACE'  // Student peer discovery
  | 'TEACHER'      // Teacher home (optimizer + insights)
  | 'INSTITUTION'  // B2B admin home
  | 'CLASS_KT';    // B2B: class-level KT drill-down

export interface TopNavbarProps {
  subjects: Subject[];
  selectedSubject: Subject | null;
  onSelectSubject: (sub: Subject) => void;
  activeView: AppView;
  onNavigate: (view: AppView) => void;
  onOpenCommandPalette: () => void;
  currentPersona: Persona;
  onOpenLoginModal: () => void;
}

export const TopNavbar: React.FC<TopNavbarProps> = ({
  subjects,
  selectedSubject,
  onSelectSubject,
  activeView,
  onNavigate,
  onOpenCommandPalette,
  currentPersona,
  onOpenLoginModal,
}) => {
  // ──────────────────────────────────────────────────────────────
  // Role-specific navigation: each user type sees ONLY their views
  // ──────────────────────────────────────────────────────────────
  const getNavItems = () => {
    if (currentPersona.role === 'LEARNER') {
      return [
        { id: 'DASHBOARD' as const, label: 'Dashboard', icon: Compass },
        { id: 'ATLAS' as const, label: 'Knowledge Atlas', icon: Orbit },
        { id: 'PATH' as const, label: 'Learning Path', icon: Map },
        { id: 'SOURCES' as const, label: 'Sources', icon: BookOpen },
        { id: 'MARKETPLACE' as const, label: 'Peer Marketplace', icon: Users },
      ];
    }

    if (currentPersona.role === 'TEACHER') {
      return [
        { id: 'TEACHER' as const, label: 'Teaching Optimizer', icon: Sparkles },
        { id: 'ATLAS' as const, label: 'Knowledge Atlas', icon: Orbit },
        { id: 'SOURCES' as const, label: 'Sources', icon: BookOpen },
      ];
    }

    // ADMIN (B2B Institutional)
    return [
      { id: 'INSTITUTION' as const, label: 'Institution', icon: Building2 },
      { id: 'CLASS_KT' as const, label: 'Class Knowledge', icon: BarChart3 },
      { id: 'TEACHER' as const, label: 'Teaching Optimizer', icon: Sparkles },
      { id: 'ATLAS' as const, label: 'Knowledge Atlas', icon: Orbit },
      { id: 'SOURCES' as const, label: 'Sources', icon: BookOpen },
    ];
  };

  const navItems = getNavItems();

  const roleBadgeStyle =
    currentPersona.role === 'LEARNER'
      ? 'bg-cyan-500/10 text-cyan-300 border-cyan-400/30'
      : currentPersona.role === 'TEACHER'
      ? 'bg-purple-500/10 text-purple-300 border-purple-400/30'
      : 'bg-blue-500/10 text-blue-300 border-blue-400/30';

  const homeView: AppView =
    currentPersona.role === 'TEACHER' ? 'TEACHER'
    : currentPersona.role === 'ADMIN' ? 'INSTITUTION'
    : 'DASHBOARD';

  return (
    <header className="sticky top-0 z-40 w-full border-b border-white/[0.07] bg-space-950/85 backdrop-blur-2xl px-4 lg:px-8 py-2.5 transition-all">
      <div className="max-w-[1600px] mx-auto flex items-center justify-between gap-4">
        
        {/* Left: Brand Identity & Subject Selector */}
        <div className="flex items-center gap-4">
          {/* Logo */}
          <div 
            className="flex items-center gap-2.5 cursor-pointer group"
            onClick={() => onNavigate(homeView)}
          >
            <div className="relative w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400/20 via-space-800 to-space-900 border border-cyan-400/40 flex items-center justify-center shadow-[0_0_16px_rgba(0,240,255,0.15)] group-hover:border-cyan-400 transition-colors">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              <div className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" style={{ animationDuration: '3s' }} />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-display font-bold text-sm tracking-tight text-white group-hover:text-cyan-300 transition-colors">
                  LEARNSENSE
                </span>
                <span className="text-[9px] font-mono text-cyan-400/80 tracking-widest px-1 py-0.2 rounded bg-cyan-950/60 border border-cyan-500/30">
                  TAPROOT
                </span>
              </div>
              <span className="text-[10px] font-mono text-universe-slate/70 tracking-widest uppercase">
                {currentPersona.role === 'LEARNER' ? 'Knowledge Universe' :
                 currentPersona.role === 'TEACHER' ? 'Instructor Intelligence' :
                 'Enterprise Platform'}
              </span>
            </div>
          </div>

          <div className="h-5 w-px bg-white/[0.08] hidden sm:block" />

          {/* Integrated Subject Selector — visible for all roles */}
          <div className="hidden sm:flex items-center gap-2">
            {selectedSubject && (
              <div className="relative group/sel">
                <select
                  value={selectedSubject.id}
                  onChange={(e) => {
                    if (e.target.value === '__UPLOAD_NEW__') {
                      onNavigate('SOURCES');
                      return;
                    }
                    const sub = subjects.find((s) => s.id === e.target.value);
                    if (sub) onSelectSubject(sub);
                  }}
                  className="pl-3 pr-8 py-1.5 rounded-lg bg-space-800/80 hover:bg-space-750 border border-white/[0.08] hover:border-cyan-500/40 text-xs text-universe-text font-medium focus:outline-none focus:border-cyan-400 cursor-pointer appearance-none transition-all max-w-[200px] truncate"
                >
                  {subjects.map((s) => (
                    <option key={s.id} value={s.id} className="bg-space-900 text-universe-text">
                      {s.title}
                    </option>
                  ))}
                  <option value="__UPLOAD_NEW__" className="bg-space-900 text-cyan-400 font-bold">
                    + Ingest New Material...
                  </option>
                </select>
                <div className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-universe-slate text-[10px]">
                  ▼
                </div>
              </div>
            )}

            <button
              onClick={() => onNavigate('SOURCES')}
              title="Inject New Material (PDF, Slides, Notes)"
              className="px-2.5 py-1.5 rounded-lg bg-space-800/50 hover:bg-cyan-500/10 border border-white/[0.07] hover:border-cyan-400/30 text-cyan-400 hover:text-cyan-300 text-xs flex items-center gap-1.5 transition-all"
            >
              <Upload className="w-3.5 h-3.5" />
              <span className="hidden md:inline font-mono text-[11px] font-semibold">+ Ingest</span>
            </button>
          </div>
        </div>

        {/* Center: Role-Specific Navigation */}
        <nav className="hidden xl:flex items-center gap-1 p-1 rounded-xl bg-space-900/60 border border-white/[0.06] backdrop-blur-md">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className={`relative px-3.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-2 transition-all duration-200 ${
                  isActive
                    ? 'text-white bg-space-750 shadow-[0_2px_12px_rgba(0,0,0,0.4)] border border-white/[0.08]'
                    : 'text-universe-slate hover:text-universe-text hover:bg-white/[0.03]'
                }`}
              >
                <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-cyan-400' : 'text-universe-slate'}`} />
                <span>{item.label}</span>
                {isActive && (
                  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-6 h-[2px] bg-cyan-400 rounded-full shadow-[0_0_8px_#00F0FF]" />
                )}
              </button>
            );
          })}
        </nav>

        {/* Right: Command Palette + Persona Pill */}
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenCommandPalette}
            className="hidden md:flex px-3 py-1.5 rounded-lg bg-space-850 hover:bg-space-750 border border-white/[0.07] text-xs text-universe-slate hover:text-universe-text items-center gap-2 transition-all shadow-sm group"
          >
            <Search className="w-3.5 h-3.5 text-universe-slate group-hover:text-cyan-400 transition-colors" />
            <span className="font-mono text-[11px]">Command</span>
            <kbd className="px-1.5 py-0.5 rounded bg-space-950 border border-white/[0.08] text-[9px] font-mono text-universe-slate flex items-center gap-0.5">
              <Command className="w-2.5 h-2.5" /> K
            </kbd>
          </button>

          {/* Persona & Login Switcher Pill */}
          <button
            onClick={onOpenLoginModal}
            title="Switch between Student, Teacher, or B2B Admin"
            className="px-3 py-1 rounded-xl bg-space-850 hover:bg-space-800 border border-white/[0.1] hover:border-cyan-400/40 text-xs flex items-center gap-2.5 transition-all shadow-sm group cursor-pointer"
          >
            <span className="text-base select-none">{currentPersona.avatar}</span>
            <div className="flex flex-col text-left">
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-white group-hover:text-cyan-300 text-xs transition-colors">
                  {currentPersona.name}
                </span>
                <span
                  className={`text-[9px] font-mono font-bold px-1.5 py-0.2 rounded-full border uppercase tracking-wider ${roleBadgeStyle}`}
                >
                  {currentPersona.role}
                </span>
              </div>
              <span className="text-[10px] text-universe-slate font-mono truncate max-w-[130px]">
                {currentPersona.title}
              </span>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-universe-slate group-hover:text-white transition-colors" />
          </button>
        </div>

      </div>

      {/* Mobile Navigation Sub-Bar */}
      <div className="flex xl:hidden items-center justify-around pt-2 mt-2 border-t border-white/[0.06] overflow-x-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`flex flex-col items-center gap-0.5 py-1 px-2.5 text-[10px] font-medium transition-colors shrink-0 ${
                isActive ? 'text-cyan-400 font-bold' : 'text-universe-slate'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>
    </header>
  );
};
