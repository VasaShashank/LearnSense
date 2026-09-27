import React from 'react';
import type { Subject } from '../../api/client';
import { Compass, BookOpen, Map, Sun, Moon, Search, Command, Upload } from 'lucide-react';

export interface TopNavbarProps {
  subjects: Subject[];
  selectedSubject: Subject | null;
  onSelectSubject: (sub: Subject) => void;
  activeView: 'DASHBOARD' | 'ATLAS' | 'PATH' | 'SOURCES';
  onNavigate: (view: 'DASHBOARD' | 'ATLAS' | 'PATH' | 'SOURCES') => void;
  onOpenCommandPalette: () => void;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
}

export const TopNavbar: React.FC<TopNavbarProps> = ({
  subjects,
  selectedSubject,
  onSelectSubject,
  activeView,
  onNavigate,
  onOpenCommandPalette,
  theme,
  onToggleTheme,
}) => {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl px-6 py-3 flex items-center justify-between gap-4">
      {/* Brand & Subject Selector */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 cursor-pointer" onClick={() => onNavigate('DASHBOARD')}>
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-cyan-500 to-emerald-400 p-0.5 shadow-glow-cyan">
            <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
              <span className="font-extrabold text-cyan-400 text-sm tracking-tighter">T</span>
            </div>
          </div>
          <span className="font-black text-white text-base tracking-tight">TAPROOT</span>
        </div>

        {/* Subject Dropdown & Upload Action */}
        <div className="flex items-center gap-2">
          {selectedSubject && (
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
              className="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-200 font-medium focus:outline-none focus:border-cyan-400 cursor-pointer"
            >
              {subjects.map((s) => (
                <option key={s.id} value={s.id} className="bg-slate-900">
                  {s.title}
                </option>
              ))}
              <option value="__UPLOAD_NEW__" className="bg-slate-900 text-cyan-400 font-bold">
                + Upload Material (PDF, Slides, Doc)...
              </option>
            </select>
          )}

          <button
            onClick={() => onNavigate('SOURCES')}
            title="Upload Material (PDF, PPTX, DOCX, Images)"
            className="p-1.5 px-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-cyan-400 hover:text-cyan-300 text-xs flex items-center gap-1 transition-all"
          >
            <Upload className="w-3.5 h-3.5" />
            <span className="hidden sm:inline font-bold text-[11px]">+ New Subject</span>
          </button>
        </div>
      </div>

      {/* Main Navigation Links */}
      <nav className="flex items-center gap-1 p-1 rounded-2xl bg-slate-900/80 border border-slate-800 text-xs">
        <button
          onClick={() => onNavigate('DASHBOARD')}
          className={`px-3.5 py-1.5 rounded-xl font-bold flex items-center gap-1.5 transition-all ${
            activeView === 'DASHBOARD'
              ? 'bg-cyan-500 text-slate-950 shadow-glow-cyan'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Compass className="w-3.5 h-3.5" />
          <span>Dashboard</span>
        </button>

        <button
          onClick={() => onNavigate('ATLAS')}
          className={`px-3.5 py-1.5 rounded-xl font-bold flex items-center gap-1.5 transition-all ${
            activeView === 'ATLAS'
              ? 'bg-cyan-500 text-slate-950 shadow-glow-cyan'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Map className="w-3.5 h-3.5" />
          <span>Learning Atlas</span>
        </button>

        <button
          onClick={() => onNavigate('PATH')}
          className={`px-3.5 py-1.5 rounded-xl font-bold flex items-center gap-1.5 transition-all ${
            activeView === 'PATH'
              ? 'bg-cyan-500 text-slate-950 shadow-glow-cyan'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Compass className="w-3.5 h-3.5" />
          <span>Learning Path</span>
        </button>

        <button
          onClick={() => onNavigate('SOURCES')}
          className={`px-3.5 py-1.5 rounded-xl font-bold flex items-center gap-1.5 transition-all ${
            activeView === 'SOURCES'
              ? 'bg-cyan-500 text-slate-950 shadow-glow-cyan'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <BookOpen className="w-3.5 h-3.5" />
          <span>Sources</span>
        </button>
      </nav>

      {/* Right Controls: Command Palette & Theme Switcher */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenCommandPalette}
          className="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-400 hover:text-white font-mono flex items-center gap-2 transition-all"
        >
          <Search className="w-3.5 h-3.5 text-slate-400" />
          <span>Search</span>
          <kbd className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300 font-sans flex items-center gap-0.5">
            <Command className="w-2.5 h-2.5" /> K
          </kbd>
        </button>

        <button
          onClick={onToggleTheme}
          className="p-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition-colors"
          title="Toggle Light/Dark Theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-cyan-400" />}
        </button>
      </div>
    </header>
  );
};
