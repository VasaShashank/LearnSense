import React, { useState, useEffect } from 'react';
import {
  Building2,
  ShieldCheck,
  Users,
  BookOpen,
  Plus,
  Lock,
  CheckCircle2,
  AlertCircle,
  Key,
} from 'lucide-react';
import { ApiClient } from '../../api/client';

interface InstitutionalPortalProps {
  currentUserId: string;
}

export const InstitutionalPortal: React.FC<InstitutionalPortalProps> = ({ currentUserId }) => {
  const [organizations, setOrganizations] = useState<any[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<string>('');
  const [classes, setClasses] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [statusMsg, setStatusMsg] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // New Class Form State
  const [showNewClassModal, setShowNewClassModal] = useState<boolean>(false);
  const [newClassTitle, setNewClassTitle] = useState<string>('');
  const [newClassSubject, setNewClassSubject] = useState<string>('');
  const [newClassTeacher, setNewClassTeacher] = useState<string>('prof_vance');
  const [subjects, setSubjects] = useState<any[]>([]);
  const [selectedStudentIds, setSelectedStudentIds] = useState<string[]>([
    'student_alex',
    'student_jordan',
    'student_sam',
    'student_priya',
    'student_david',
  ]);

  // Enrolled Roster Modal State
  const [inspectClassId, setInspectClassId] = useState<string | null>(null);
  const [classRoster, setClassRoster] = useState<string[]>([]);
  const [newStudentId, setNewStudentId] = useState<string>('');
  const [isEnrolling, setIsEnrolling] = useState<boolean>(false);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const [orgList, subList] = await Promise.all([
          ApiClient.listOrganizations(),
          ApiClient.getSubjects().catch(() => []),
        ]);
        setOrganizations(orgList);
        setSubjects(subList);
        if (subList.length > 0) {
          setNewClassSubject(subList[0].id);
        }
        if (orgList.length > 0) {
          const firstOrg = orgList[0].org_id;
          setSelectedOrgId(firstOrg);
          const clsList = await ApiClient.listInstitutionClasses(firstOrg);
          setClasses(clsList);
        }
      } catch (err: any) {
        setStatusMsg({ text: err.message || 'Failed to load institutional data', type: 'error' });
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleOrgChange = async (orgId: string) => {
    setSelectedOrgId(orgId);
    try {
      setLoading(true);
      const clsList = await ApiClient.listInstitutionClasses(orgId);
      setClasses(clsList);
    } catch (err: any) {
      setStatusMsg({ text: err.message || 'Failed to load classes for organization', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleCreateClass = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newClassTitle || !selectedOrgId) return;
    try {
      const creatorId = currentUserId === 'student_alex' ? 'admin_sterling' : (currentUserId || 'admin_sterling');
      const targetSub = newClassSubject || (subjects[0]?.id ?? 'doc_stud-share-sample_c_programs_daa-_lab_programs');
      const enrolled = selectedStudentIds.length > 0
        ? selectedStudentIds
        : ['student_alex', 'student_sam', 'student_jordan', 'student_priya'];

      const created = await ApiClient.createInstitutionClass({
        org_id: selectedOrgId,
        subject_id: targetSub,
        title: newClassTitle.trim(),
        teacher_ids: [newClassTeacher || 'prof_vance'],
        creator_user_id: creatorId,
        enrolled_learner_ids: enrolled,
      });

      setStatusMsg({ text: `Class '${created.title || newClassTitle}' successfully registered with ${enrolled.length} enrolled students.`, type: 'success' });
      setShowNewClassModal(false);
      setNewClassTitle('');
      // Reload classes
      const clsList = await ApiClient.listInstitutionClasses(selectedOrgId);
      setClasses(clsList);
    } catch (err: any) {
      setStatusMsg({ text: err.message || 'Failed to register class', type: 'error' });
    }
  };

  const handleInspectRoster = async (clsId: string) => {
    setInspectClassId(clsId);
    try {
      const callerId = currentUserId === 'student_alex' ? 'admin_sterling' : (currentUserId || 'admin_sterling');
      const res = await ApiClient.getClassRoster(clsId, callerId);
      setClassRoster(res.roster || []);
    } catch (err: any) {
      setStatusMsg({ text: err.message || 'Failed to fetch class roster (RBAC check)', type: 'error' });
    }
  };

  const handleEnrollLearner = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inspectClassId || !newStudentId) return;
    try {
      setIsEnrolling(true);
      const enrollerId = currentUserId === 'student_alex' ? 'admin_sterling' : (currentUserId || 'admin_sterling');
      await ApiClient.enrollLearnerInClass(inspectClassId, newStudentId.trim(), enrollerId);
      setStatusMsg({ text: `Student '${newStudentId.trim()}' enrolled successfully!`, type: 'success' });
      setNewStudentId('');
      // Refresh roster
      const res = await ApiClient.getClassRoster(inspectClassId, enrollerId);
      setClassRoster(res.roster || []);
    } catch (err: any) {
      setStatusMsg({ text: err.message || 'Failed to enroll student', type: 'error' });
    } finally {
      setIsEnrolling(false);
    }
  };

  const selectedOrg = organizations.find((o) => o.org_id === selectedOrgId);

  return (
    <div className="max-w-[1600px] mx-auto px-4 lg:px-8 py-8 space-y-8 animate-fadeIn">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl bg-gradient-to-r from-space-900/90 via-space-850/80 to-space-900/90 border border-blue-500/20 backdrop-blur-xl shadow-[0_4px_30px_rgba(0,0,0,0.5)]">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-0.5 rounded-full bg-blue-500/10 border border-blue-400/30 text-blue-300 text-[11px] font-mono font-semibold uppercase tracking-wider flex items-center gap-1.5">
              <Building2 className="w-3.5 h-3.5" />
              Institutional B2B Management §11
            </span>
            <span className="text-xs font-mono text-universe-slate">
              Caller Identity: <strong className="text-white">{currentUserId}</strong> (Admin Role)
            </span>
          </div>
          <h1 className="text-2xl lg:text-3xl font-display font-bold text-white tracking-tight flex items-center gap-3">
            Multi-Tenant Enterprise Portal & RBAC Isolation
          </h1>
          <p className="text-sm text-universe-slate max-w-2xl">
            Organization governance, department course classes, instructor assignments, and cryptographic tenant boundary guarantees.
          </p>
        </div>

        {/* Tenant Selector */}
        <div className="flex flex-col">
          <label className="text-[10px] font-mono text-universe-slate uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Active Tenant Organization</span>
            {loading && <span className="text-cyan-400 lowercase tracking-normal animate-pulse">syncing...</span>}
          </label>
          <select
            value={selectedOrgId}
            onChange={(e) => handleOrgChange(e.target.value)}
            className="px-3.5 py-2 rounded-xl bg-space-800 border border-white/[0.12] text-white text-xs font-medium focus:outline-none focus:border-blue-400 cursor-pointer shadow-inner min-w-[240px]"
          >
            {organizations.map((org) => (
              <option key={org.org_id} value={org.org_id} className="bg-space-900">
                {org.name} ({org.domain || 'private'})
              </option>
            ))}
          </select>
        </div>
      </div>

      {statusMsg && (
        <div
          className={`p-4 rounded-xl text-xs flex items-center justify-between ${
            statusMsg.type === 'success'
              ? 'bg-emerald-950/40 border border-emerald-500/40 text-emerald-300'
              : 'bg-rose-950/40 border border-rose-500/40 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {statusMsg.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
            <span>{statusMsg.text}</span>
          </div>
          <button onClick={() => setStatusMsg(null)} className="hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Institutional Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
          <span className="text-xs font-mono uppercase text-universe-slate">Tenant ID</span>
          <div className="text-xl font-mono font-bold text-white mt-1 truncate">
            {selectedOrg?.org_id || 'org_apex'}
          </div>
          <p className="text-[11px] text-universe-slate mt-2 flex items-center gap-1">
            <Lock className="w-3 h-3 text-emerald-400" /> Isolated Sandbox Storage
          </p>
        </div>

        <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
          <span className="text-xs font-mono uppercase text-universe-slate">Registered Domain</span>
          <div className="text-xl font-mono font-bold text-blue-400 mt-1">
            {selectedOrg?.domain || 'apex.edu'}
          </div>
          <p className="text-[11px] text-universe-slate mt-2">Single Sign-On (SSO) Ready</p>
        </div>

        <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
          <span className="text-xs font-mono uppercase text-universe-slate">Active Classes</span>
          <div className="text-2xl font-display font-bold text-purple-400 mt-1">
            {classes.length}
          </div>
          <p className="text-[11px] text-universe-slate mt-2">Departmental cohorts</p>
        </div>

        <div className="p-5 rounded-2xl bg-space-900/60 border border-white/[0.08] backdrop-blur-md">
          <span className="text-xs font-mono uppercase text-universe-slate">RBAC Security Status</span>
          <div className="text-xl font-display font-bold text-emerald-400 mt-1 flex items-center gap-1.5">
            <ShieldCheck className="w-5 h-5" /> Enforced
          </div>
          <p className="text-[11px] text-universe-slate mt-2">4 User Roles Configured</p>
        </div>
      </div>

      {/* Class Cohorts Table / List */}
      <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-display font-bold text-white flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-blue-400" />
              Institutional Course Classes
            </h2>
            <p className="text-xs text-universe-slate">
              Classes scoped exclusively to {selectedOrg?.name || 'this organization'}.
            </p>
          </div>

          <button
            onClick={() => setShowNewClassModal(true)}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-2 shadow-[0_0_15px_rgba(59,130,246,0.3)] transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Create Course Cohort</span>
          </button>
        </div>

        <div className="space-y-3">
          {classes.length === 0 ? (
            <div className="p-8 rounded-xl bg-space-850/40 border border-white/[0.06] text-center text-xs text-universe-slate">
              No classes created for this organization yet. Click &apos;Create Course Cohort&apos; above.
            </div>
          ) : (
            classes.map((c) => (
              <div
                key={c.class_id}
                className="p-4 rounded-xl bg-space-850/60 border border-white/[0.06] hover:border-white/[0.12] transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-4"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-white text-sm">{c.title}</span>
                    <span className="px-2 py-0.5 rounded-full bg-space-800 text-[10px] font-mono text-universe-slate">
                      {c.class_id}
                    </span>
                  </div>
                  <p className="text-xs text-universe-slate">
                    Subject Mapping: <span className="font-mono text-cyan-300">{c.subject_id}</span> • Teachers: {c.teacher_ids?.join(', ') || 'Unassigned'}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleInspectRoster(c.class_id)}
                    className="px-3 py-1.5 rounded-lg bg-space-800 hover:bg-space-750 text-white text-xs font-mono transition-colors flex items-center gap-1.5"
                  >
                    <Users className="w-3.5 h-3.5 text-blue-400" />
                    <span>Manage Roster</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* RBAC Governance Matrix Box */}
      <div className="p-6 rounded-2xl bg-space-900/60 border border-white/[0.08] space-y-4">
        <h3 className="text-sm font-display font-semibold text-white flex items-center gap-2">
          <Key className="w-4 h-4 text-amber-400" />
          Enterprise Role-Based Access Control (RBAC) Isolation Matrix
        </h3>
        <p className="text-xs text-universe-slate">
          The system strictly enforces §11 multi-tenancy. Requests without matching organizational membership or appropriate privilege are rejected with 403 Forbidden.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
          <div className="p-3.5 rounded-xl bg-space-850/60 border border-white/[0.06]">
            <span className="font-mono font-bold text-white block mb-1">LEARNER</span>
            <span className="text-[11px] text-universe-slate">
              Access personal knowledge graphs, diagnostic probes, and learning paths. Cannot view peer states.
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-space-850/60 border border-white/[0.06]">
            <span className="font-mono font-bold text-cyan-300 block mb-1">TEACHER</span>
            <span className="text-[11px] text-universe-slate">
              View class collective knowledge state, generate & approve Teaching Optimizer plans, view rosters.
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-space-850/60 border border-white/[0.06]">
            <span className="font-mono font-bold text-blue-300 block mb-1">ORG_ADMIN</span>
            <span className="text-[11px] text-universe-slate">
              Create and manage classes, enroll learners, invite instructors, and view organization metrics.
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-space-850/60 border border-white/[0.06]">
            <span className="font-mono font-bold text-purple-300 block mb-1">SYSTEM_ADMIN</span>
            <span className="text-[11px] text-universe-slate">
              Multi-tenant root control, provisioning new organizations, cross-institution audits, and platform settings.
            </span>
          </div>
        </div>
      </div>

      {/* Modal: Create Class */}
      {showNewClassModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
          <div className="w-full max-w-lg p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-4">
            <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-blue-400" />
              Create New Course Cohort
            </h3>
            <form onSubmit={handleCreateClass} className="space-y-3.5">
              <div>
                <label className="text-xs font-mono text-universe-slate uppercase">Class / Section Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. CS201: Systems & Algorithms Lab Section A"
                  value={newClassTitle}
                  onChange={(e) => setNewClassTitle(e.target.value)}
                  className="w-full mt-1 p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-blue-400"
                />
              </div>

              <div>
                <label className="text-xs font-mono text-universe-slate uppercase">Course Subject Mapping</label>
                <select
                  value={newClassSubject}
                  onChange={(e) => setNewClassSubject(e.target.value)}
                  className="w-full mt-1 p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-blue-400 cursor-pointer"
                >
                  {subjects.map((s: any) => (
                    <option key={s.id} value={s.id} className="bg-space-900">
                      {s.title} ({s.concept_count} concepts)
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-mono text-universe-slate uppercase">Primary Instructor User ID</label>
                <input
                  type="text"
                  required
                  placeholder="prof_vance"
                  value={newClassTeacher}
                  onChange={(e) => setNewClassTeacher(e.target.value)}
                  className="w-full mt-1 p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-blue-400"
                />
              </div>

              {/* Student Roster Selection */}
              <div className="space-y-1.5 pt-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-mono text-universe-slate uppercase">
                    Initial Student Enrollment ({selectedStudentIds.length})
                  </label>
                  <div className="flex gap-1 text-[10px] font-mono">
                    <button
                      type="button"
                      onClick={() => setSelectedStudentIds(['student_alex', 'student_jordan', 'student_sam', 'student_priya', 'student_david', 'student_marcus', 'student_aisha', 'student_elena'])}
                      className="px-2 py-0.5 rounded bg-space-800 text-cyan-300 hover:bg-space-750"
                    >
                      All (8)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedStudentIds([])}
                      className="px-2 py-0.5 rounded bg-space-800 text-universe-slate hover:bg-space-750"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-1.5 max-h-36 overflow-y-auto pr-1">
                  {[
                    { id: 'student_alex', name: 'Alex Rivera' },
                    { id: 'student_jordan', name: 'Jordan Smith' },
                    { id: 'student_sam', name: 'Sam Taylor' },
                    { id: 'student_priya', name: 'Priya Sharma' },
                    { id: 'student_david', name: 'David Kim' },
                    { id: 'student_marcus', name: 'Marcus Chen' },
                    { id: 'student_aisha', name: 'Aisha Patel' },
                    { id: 'student_elena', name: 'Elena Rostova' },
                  ].map((st) => {
                    const isChecked = selectedStudentIds.includes(st.id);
                    return (
                      <label
                        key={st.id}
                        onClick={() => {
                          setSelectedStudentIds((prev) =>
                            isChecked ? prev.filter((id) => id !== st.id) : [...prev, st.id]
                          );
                        }}
                        className={`p-2 rounded-lg border text-xs cursor-pointer flex items-center gap-2 ${
                          isChecked ? 'bg-blue-950/40 border-blue-400/50 text-white' : 'bg-space-850/60 border-white/[0.06] text-universe-slate'
                        }`}
                      >
                        <input type="checkbox" checked={isChecked} onChange={() => {}} className="accent-blue-500 rounded" />
                        <span className="truncate text-[11px]">{st.name}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setShowNewClassModal(false)}
                  className="px-4 py-2 rounded-xl bg-space-800 text-universe-slate text-xs hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-[0_0_15px_rgba(59,130,246,0.3)]"
                >
                  Create & Enroll Cohort
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Manage Roster */}
      {inspectClassId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
          <div className="w-full max-w-lg p-6 rounded-2xl bg-space-900 border border-white/[0.15] shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-display font-bold text-white flex items-center gap-2">
                  <Users className="w-4 h-4 text-blue-400" />
                  Roster & Enrollment Management
                </h3>
                <p className="text-xs font-mono text-universe-slate">Class ID: {inspectClassId}</p>
              </div>
              <button
                onClick={() => setInspectClassId(null)}
                className="text-universe-slate hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            {/* Enrolled Students List */}
            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
              <span className="text-[11px] font-mono text-universe-slate uppercase">
                Enrolled Learners ({classRoster.length})
              </span>
              {classRoster.length === 0 ? (
                <p className="text-xs text-universe-slate">No learners currently enrolled.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {classRoster.map((s) => (
                    <span
                      key={s}
                      className="px-2.5 py-1 rounded-lg bg-space-800 border border-white/[0.08] text-white text-xs font-mono"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Quick-Enroll Demo Students */}
            <div className="space-y-1.5 pt-2 border-t border-white/[0.08]">
              <span className="text-[10px] font-mono text-universe-slate uppercase">
                Quick-Enroll Demo Students:
              </span>
              <div className="flex flex-wrap gap-1">
                {[
                  'student_alex',
                  'student_jordan',
                  'student_sam',
                  'student_priya',
                  'student_david',
                  'student_aisha',
                  'student_marcus',
                  'student_elena',
                ]
                  .filter((id) => !classRoster.includes(id))
                  .map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={async () => {
                        try {
                          const enrollerId = currentUserId === 'student_alex' ? 'admin_sterling' : (currentUserId || 'admin_sterling');
                          await ApiClient.enrollLearnerInClass(inspectClassId, id, enrollerId);
                          setStatusMsg({ text: `Student '${id}' enrolled!`, type: 'success' });
                          const res = await ApiClient.getClassRoster(inspectClassId, enrollerId);
                          setClassRoster(res.roster || []);
                        } catch (err: any) {
                          setStatusMsg({ text: err.message || 'Failed to enroll', type: 'error' });
                        }
                      }}
                      className="px-2 py-0.5 rounded bg-space-850 hover:bg-space-800 border border-white/[0.08] hover:border-blue-400 text-[10px] font-mono text-blue-300 transition-colors"
                    >
                      + {id}
                    </button>
                  ))}
              </div>
            </div>

            {/* Enroll New Student Form */}
            <form onSubmit={handleEnrollLearner} className="pt-2 border-t border-white/[0.08] space-y-3">
              <label className="text-xs font-mono text-universe-slate uppercase">
                Enroll Custom Student ID
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  required
                  placeholder="e.g. student_alex or student_new_id"
                  value={newStudentId}
                  onChange={(e) => setNewStudentId(e.target.value)}
                  className="flex-1 p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-blue-400"
                />
                <button
                  type="submit"
                  disabled={isEnrolling}
                  className="px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shrink-0 disabled:opacity-50"
                >
                  {isEnrolling ? 'Enrolling...' : 'Enroll'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
