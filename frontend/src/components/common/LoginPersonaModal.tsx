import React, { useState } from 'react';
import {
  Check,
  ArrowRight,
  X,
} from 'lucide-react';

export interface Persona {
  id: string;
  name: string;
  role: 'LEARNER' | 'TEACHER' | 'ADMIN';
  title: string;
  avatar: string;
  org_name: string;
  email: string;
}

interface LoginPersonaModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentPersona: Persona;
  onSelectPersona: (p: Persona) => void;
}

export const PRESET_PERSONAS: Persona[] = [
  {
    id: 'student_alex',
    name: 'Alex Rivera',
    role: 'LEARNER',
    title: 'Undergraduate Scholar',
    avatar: '👨‍🎓',
    org_name: 'Apex Institute of Science & Technology',
    email: 'alex.rivera@apex.edu',
  },
  {
    id: 'prof_vance',
    name: 'Prof. Eleanor Vance',
    role: 'TEACHER',
    title: 'Lead Instructor, Systems & DAA',
    avatar: '👩‍🏫',
    org_name: 'Apex Institute of Science & Technology',
    email: 'e.vance@apex.edu',
  },
  {
    id: 'admin_sterling',
    name: 'Dr. Marcus Sterling',
    role: 'ADMIN',
    title: 'Dean of Academic Systems (B2B Admin)',
    avatar: '🏛️',
    org_name: 'Apex Institute of Science & Technology',
    email: 'm.sterling@apex.edu',
  },
  {
    id: 'teacher_independent',
    name: 'Dr. Sarah Lin',
    role: 'TEACHER',
    title: 'Independent Visiting Educator',
    avatar: '🧑‍🏫',
    org_name: 'Open Academic Community (Non-B2B)',
    email: 'sarah.lin@open-ed.org',
  },
];

export const LoginPersonaModal: React.FC<LoginPersonaModalProps> = ({
  isOpen,
  onClose,
  currentPersona,
  onSelectPersona,
}) => {
  const [customUserId, setCustomUserId] = useState<string>('');
  const [customRole, setCustomRole] = useState<'LEARNER' | 'TEACHER' | 'ADMIN'>('LEARNER');

  if (!isOpen) return null;

  const handleCustomLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customUserId.trim()) return;
    const persona: Persona = {
      id: customUserId.trim(),
      name: customUserId.trim(),
      role: customRole,
      title: `${customRole} Account`,
      avatar: customRole === 'TEACHER' ? '👩‍🏫' : customRole === 'ADMIN' ? '🏛️' : '👨‍🎓',
      org_name: 'Apex Institute of Science & Technology',
      email: `${customUserId.trim()}@apex.edu`,
    };
    onSelectPersona(persona);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-fadeIn">
      <div className="w-full max-w-xl p-6 sm:p-8 rounded-3xl bg-space-900 border border-white/[0.12] shadow-2xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <span className="px-2.5 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-400/30 text-cyan-300 text-[10px] font-mono uppercase tracking-wider">
              Identity & Access Management
            </span>
            <h2 className="text-xl font-display font-bold text-white">
              Switch Persona & Role
            </h2>
            <p className="text-xs text-universe-slate">
              Switch between Student, Teacher, and Institutional B2B Admin roles to test permissions.
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-universe-slate hover:text-white hover:bg-space-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Persona Preset Cards */}
        <div className="space-y-3">
          <label className="text-[11px] font-mono uppercase text-universe-slate tracking-wider">
            Select Active Profile
          </label>
          <div className="space-y-2.5">
            {PRESET_PERSONAS.map((p) => {
              const isSelected = p.id === currentPersona.id;
              const roleBadgeColor =
                p.role === 'LEARNER'
                  ? 'bg-cyan-500/10 text-cyan-300 border-cyan-400/30'
                  : p.role === 'TEACHER'
                  ? 'bg-purple-500/10 text-purple-300 border-purple-400/30'
                  : 'bg-blue-500/10 text-blue-300 border-blue-400/30';

              return (
                <div
                  key={p.id}
                  onClick={() => {
                    onSelectPersona(p);
                    onClose();
                  }}
                  className={`p-4 rounded-2xl border transition-all cursor-pointer flex items-center justify-between gap-4 ${
                    isSelected
                      ? 'bg-space-800 border-cyan-400/50 shadow-[0_0_20px_rgba(0,240,255,0.15)] ring-1 ring-cyan-400/50'
                      : 'bg-space-850/60 border-white/[0.06] hover:bg-space-800/80 hover:border-white/[0.12]'
                  }`}
                >
                  <div className="flex items-center gap-3.5">
                    <span className="text-2xl p-2 rounded-xl bg-space-900 border border-white/[0.06]">
                      {p.avatar}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-white text-sm">{p.name}</span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[9px] font-mono font-bold uppercase tracking-wider border ${roleBadgeColor}`}
                        >
                          {p.role}
                        </span>
                      </div>
                      <p className="text-xs text-universe-slate">{p.title}</p>
                      <p className="text-[10px] font-mono text-universe-slate/70">
                        {p.email} • {p.org_name}
                      </p>
                    </div>
                  </div>

                  {isSelected ? (
                    <div className="w-7 h-7 rounded-full bg-cyan-400/20 border border-cyan-400/50 flex items-center justify-center text-cyan-400">
                      <Check className="w-4 h-4" />
                    </div>
                  ) : (
                    <div className="text-universe-slate hover:text-white text-xs flex items-center gap-1 font-mono">
                      <span>Switch</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Custom User ID Login Input */}
        <form onSubmit={handleCustomLogin} className="pt-3 border-t border-white/[0.08] space-y-3">
          <label className="text-[11px] font-mono uppercase text-universe-slate tracking-wider block">
            Or Sign In with Custom User ID
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="e.g. user_faculty_demo"
              value={customUserId}
              onChange={(e) => setCustomUserId(e.target.value)}
              className="flex-1 p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-cyan-400"
            />
            <select
              value={customRole}
              onChange={(e) => setCustomRole(e.target.value as any)}
              className="px-3 py-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-cyan-400 cursor-pointer"
            >
              <option value="LEARNER">Learner</option>
              <option value="TEACHER">Teacher</option>
              <option value="ADMIN">Org Admin</option>
            </select>
            <button
              type="submit"
              className="px-4 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-space-950 font-bold text-xs shadow-md transition-all shrink-0"
            >
              Log In
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
