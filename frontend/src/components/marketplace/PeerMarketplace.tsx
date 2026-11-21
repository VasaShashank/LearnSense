import React, { useState, useEffect, useMemo } from 'react';
import {
  Users,
  Search,
  Sparkles,
  CheckCircle2,
  Star,
  Zap,
  ShieldCheck,
  UserPlus,
  Award,
  Target,
  Heart,
  Filter,
  MessageCircle,
  RefreshCw,
} from 'lucide-react';
import type { Subject } from '../../api/client';
import { ApiClient } from '../../api/client';

export interface PeerProfile {
  learner_id: string;
  display_name: string;
  avatar_emoji: string;
  role?: string;
  specialty?: string;
  strengths: string[];
  learning_goals: string[];
  mastery_avg: number;
  subjects: string[];
  match_score: number;
  online_status: 'online' | 'idle' | 'offline';
}

export interface ConnectionRecord {
  id: string;
  from_id: string;
  to_id: string;
  from_name: string;
  from_avatar: string;
  topic: string;
  message: string;
  status: 'PENDING' | 'ACCEPTED' | 'DECLINED';
  created_at: string;
}

interface PeerMarketplaceProps {
  learnerId: string;
  subjects: Subject[];
  selectedSubject: Subject | null;
}

export const PeerMarketplace: React.FC<PeerMarketplaceProps> = ({
  learnerId,
  subjects: _subjects,
  selectedSubject,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterTopic, setFilterTopic] = useState<string>('');
  const [peers, setPeers] = useState<PeerProfile[]>([]);
  const [isLoadingPeers, setIsLoadingPeers] = useState<boolean>(true);
  const [connections, setConnections] = useState<{ incoming: ConnectionRecord[]; outgoing: ConnectionRecord[]; all: ConnectionRecord[] }>({
    incoming: [],
    outgoing: [],
    all: [],
  });
  const [sentRequests, setSentRequests] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<'DISCOVER' | 'CONNECTIONS' | 'MY_PROFILE'>('DISCOVER');
  const [connectMessage, setConnectMessage] = useState('');
  const [connectingPeerId, setConnectingPeerId] = useState<string | null>(null);

  // Load authentic peers and connections from persistent backend
  const loadMarketplaceData = React.useCallback(async () => {
    setIsLoadingPeers(true);
    try {
      const [fetchedPeers, connsData] = await Promise.all([
        ApiClient.getMarketplacePeers(selectedSubject?.id),
        ApiClient.getMarketplaceConnections().catch(() => ({ incoming: [], outgoing: [], all: [] })),
      ]);

      if (Array.isArray(fetchedPeers) && fetchedPeers.length > 0) {
        setPeers(fetchedPeers);
      }
      if (connsData) {
        setConnections(connsData);
        const sentIds = new Set<string>((connsData.outgoing || []).map((c: any) => c.to_id));
        setSentRequests(sentIds);
      }
    } catch (err) {
      console.warn('Failed to load marketplace peers:', err);
    } finally {
      setIsLoadingPeers(false);
    }
  }, [selectedSubject?.id]);

  useEffect(() => {
    loadMarketplaceData();
  }, [loadMarketplaceData]);

  // Extract distinct topics/strengths from loaded peers for the filter dropdown
  const availableTopics = useMemo(() => {
    const topicSet = new Set<string>();
    peers.forEach(p => {
      p.strengths.forEach(s => topicSet.add(s));
    });
    return Array.from(topicSet).sort();
  }, [peers]);

  // Filter and sort peers by match score
  const filteredPeers = useMemo(() => {
    let result = [...peers];
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(p =>
        p.display_name.toLowerCase().includes(q) ||
        p.strengths.some(s => s.toLowerCase().includes(q)) ||
        p.learning_goals.some(g => g.toLowerCase().includes(q))
      );
    }
    if (filterTopic) {
      result = result.filter(p =>
        p.strengths.some(s => s.toLowerCase().includes(filterTopic.toLowerCase())) ||
        p.learning_goals.some(g => g.toLowerCase().includes(filterTopic.toLowerCase()))
      );
    }
    return result.sort((a, b) => b.match_score - a.match_score);
  }, [peers, searchQuery, filterTopic]);

  // Send persistent connection request
  const handleSendRequest = async (peer: PeerProfile) => {
    try {
      await ApiClient.sendMarketplaceConnection({
        to_id: peer.learner_id,
        topic: peer.strengths[0] || 'Concept Discussion',
        message: connectMessage.trim() || `Hey ${peer.display_name}, I'd love to study ${peer.strengths[0] || 'concepts'} together!`,
      });
      setSentRequests(prev => new Set([...prev, peer.learner_id]));
      setConnectingPeerId(null);
      setConnectMessage('');
      loadMarketplaceData();
    } catch (err) {
      console.error('Failed to send connection request:', err);
    }
  };

  // Respond to connection request (Accept / Decline)
  const handleRespondToRequest = async (reqId: string, accept: boolean) => {
    try {
      await ApiClient.respondMarketplaceConnection(reqId, accept);
      loadMarketplaceData();
    } catch (err) {
      console.error('Failed to respond to connection request:', err);
    }
  };

  const pendingIncoming = connections.incoming.filter(r => r.status === 'PENDING');
  const acceptedConnections = connections.all.filter(r => r.status === 'ACCEPTED');

  const statusDotColor = (s: PeerProfile['online_status']) =>
    s === 'online' ? 'bg-emerald-400' : s === 'idle' ? 'bg-amber-400' : 'bg-zinc-500';

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header Banner */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-space-900/90 via-purple-950/30 to-space-900/90 border border-purple-500/20 backdrop-blur-xl shadow-[0_4px_30px_rgba(0,0,0,0.5)]">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5">
              <span className="px-2.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-400/30 text-purple-300 text-[11px] font-mono font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5" />
                Collaborative Knowledge Exchange
              </span>
              {pendingIncoming.length > 0 && (
                <span className="px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-400/40 text-amber-300 text-[10px] font-mono font-bold animate-pulse">
                  {pendingIncoming.length} pending request{pendingIncoming.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <h1 className="text-2xl lg:text-3xl font-display font-bold text-white tracking-tight">
              Student Peer Marketplace
            </h1>
            <p className="text-sm text-universe-slate max-w-2xl">
              Connect with peers studying {selectedSubject?.title || 'JEE STEM curriculum'}. Complementary skill matching pairs your learning goals with verified peer strengths.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-purple-500/10 border border-purple-400/20 text-center">
              <div className="text-2xl font-display font-bold text-purple-300">{peers.length}</div>
              <div className="text-[10px] font-mono text-universe-slate uppercase">Active Peers</div>
            </div>
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-400/20 text-center">
              <div className="text-2xl font-display font-bold text-emerald-300">{acceptedConnections.length}</div>
              <div className="text-[10px] font-mono text-universe-slate uppercase">Partners</div>
            </div>
            <button
              onClick={loadMarketplaceData}
              className="p-3 rounded-xl bg-space-800 hover:bg-space-750 text-universe-slate hover:text-white border border-white/[0.08] transition-colors"
              title="Refresh peer discovery"
            >
              <RefreshCw className={`w-4 h-4 ${isLoadingPeers ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="flex items-center gap-2 border-b border-white/[0.08] pb-1">
        <button
          onClick={() => setActiveTab('DISCOVER')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
            activeTab === 'DISCOVER'
              ? 'bg-purple-500/15 text-purple-300 border border-purple-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <Search className="w-4 h-4" />
          <span>Discover Peers</span>
          <span className="px-1.5 py-0.5 rounded-full bg-space-800 text-[10px] font-mono text-universe-slate">
            {filteredPeers.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('CONNECTIONS')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
            activeTab === 'CONNECTIONS'
              ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <Heart className="w-4 h-4" />
          <span>Connections & Requests</span>
          {pendingIncoming.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-400/30 text-[10px] font-mono text-amber-300 font-bold">
              {pendingIncoming.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('MY_PROFILE')}
          className={`px-4 py-2.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition-all ${
            activeTab === 'MY_PROFILE'
              ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-400/30'
              : 'text-universe-slate hover:text-white hover:bg-white/[0.03]'
          }`}
        >
          <Award className="w-4 h-4" />
          <span>My Profile & Skills</span>
        </button>
      </div>

      {/* TAB 1: DISCOVER PEERS */}
      {activeTab === 'DISCOVER' && (
        <div className="space-y-5 animate-fade-in">
          {/* Search & Filter Bar */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-universe-slate" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by peer name, concept strength, or learning goal..."
                className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-purple-400 transition-colors"
              />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-universe-slate" />
              <select
                value={filterTopic}
                onChange={(e) => setFilterTopic(e.target.value)}
                className="px-3 py-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-purple-400 cursor-pointer max-w-xs"
              >
                <option value="">All Topics ({availableTopics.length})</option>
                {availableTopics.slice(0, 15).map((topic) => (
                  <option key={topic} value={topic}>
                    {topic}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Privacy Consent Notice */}
          <div className="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/20 text-xs text-emerald-300/90 flex items-start gap-2.5">
            <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-400 mt-0.5" />
            <span>
              <strong>Curriculum Grounded & Consent-Gated:</strong> Peer skills are evaluated against verified JEE Main / NCERT syllabus masteries. Exact assessment logs remain strictly private.
            </span>
          </div>

          {/* Peer Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredPeers.map((peer) => {
              const isSent = sentRequests.has(peer.learner_id);
              const isConnecting = connectingPeerId === peer.learner_id;

              return (
                <div
                  key={peer.learner_id}
                  className="p-5 rounded-2xl bg-space-900/70 border border-white/[0.08] hover:border-purple-400/30 transition-all space-y-4 group"
                >
                  {/* Peer Header */}
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="relative">
                        <span className="text-2xl p-2 rounded-xl bg-space-800 border border-white/[0.06] block">
                          {peer.avatar_emoji}
                        </span>
                        <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-space-900 ${statusDotColor(peer.online_status)}`} />
                      </div>
                      <div>
                        <h3 className="font-semibold text-white text-sm">{peer.display_name}</h3>
                        <p className="text-[11px] text-universe-slate font-mono">
                          {peer.role || 'Peer Scholar'}
                          {peer.specialty ? ` • ${peer.specialty}` : ''}
                        </p>
                        <p className="text-[10px] text-universe-slate font-mono mt-0.5">
                          Avg Mastery: <span className="text-cyan-300">{Math.round(peer.mastery_avg * 100)}%</span>
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-purple-500/10 border border-purple-400/20">
                      <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                      <span className="text-xs font-mono font-bold text-purple-300">
                        {Math.round(peer.match_score * 100)}% match
                      </span>
                    </div>
                  </div>

                  {/* Strengths */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-emerald-400 uppercase tracking-wider">
                      <Star className="w-3 h-3" />
                      Verified Strengths (Can Teach You)
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {peer.strengths.slice(0, 4).map((s) => (
                        <span key={s} className="px-2 py-0.5 rounded-lg bg-emerald-950/40 border border-emerald-500/20 text-emerald-300 text-[10px] font-medium">
                          {s}
                        </span>
                      ))}
                      {peer.strengths.length > 4 && (
                        <span className="px-2 py-0.5 rounded-lg bg-space-800 text-universe-slate text-[10px]">
                          +{peer.strengths.length - 4} more
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Learning Goals */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-amber-400 uppercase tracking-wider">
                      <Target className="w-3 h-3" />
                      Active Goals (Seeking Study Buddy)
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {peer.learning_goals.slice(0, 3).map((g) => (
                        <span key={g} className="px-2 py-0.5 rounded-lg bg-amber-950/30 border border-amber-500/20 text-amber-300 text-[10px] font-medium">
                          {g}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Connection Action */}
                  <div className="pt-2 border-t border-white/[0.06]">
                    {isSent ? (
                      <div className="flex items-center gap-2 text-xs text-cyan-300 font-mono py-1">
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                        <span>Request Sent — Pending Peer Acceptance</span>
                      </div>
                    ) : isConnecting ? (
                      <div className="space-y-2">
                        <textarea
                          rows={2}
                          value={connectMessage}
                          onChange={(e) => setConnectMessage(e.target.value)}
                          placeholder={`Hey ${peer.display_name}, I saw your strength in ${peer.strengths[0] || 'this subject'}. Let's study together!`}
                          className="w-full p-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-purple-400"
                        />
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setConnectingPeerId(null)}
                            className="px-3 py-1.5 rounded-lg text-universe-slate text-xs hover:text-white transition-colors"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => handleSendRequest(peer)}
                            className="px-4 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(168,85,247,0.3)]"
                          >
                            <MessageCircle className="w-3.5 h-3.5" />
                            Send Request
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConnectingPeerId(peer.learner_id)}
                        className="w-full px-4 py-2 rounded-xl bg-space-800 hover:bg-purple-500/15 border border-white/[0.08] hover:border-purple-400/30 text-white text-xs font-medium flex items-center justify-center gap-2 transition-all group-hover:shadow-[0_0_12px_rgba(168,85,247,0.1)]"
                      >
                        <UserPlus className="w-3.5 h-3.5 text-purple-400" />
                        Connect to Learn Together
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {filteredPeers.length === 0 && !isLoadingPeers && (
            <div className="p-10 rounded-2xl bg-space-900/40 border border-white/[0.06] text-center space-y-2">
              <Users className="w-8 h-8 text-universe-slate mx-auto" />
              <p className="text-sm text-universe-slate">No peers match your search criteria.</p>
              <p className="text-xs text-universe-slate/60">Try clearing topic filters or searching for another subject.</p>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: CONNECTIONS & REQUESTS */}
      {activeTab === 'CONNECTIONS' && (
        <div className="space-y-6 animate-fade-in">
          {/* Incoming Requests */}
          <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-4">
            <h3 className="text-sm font-display font-semibold text-white flex items-center gap-2">
              <Zap className="w-4 h-4 text-amber-400" />
              Incoming Connection Requests
            </h3>

            {pendingIncoming.length === 0 ? (
              <div className="p-5 rounded-xl bg-space-850/40 border border-white/[0.06] text-center text-xs text-universe-slate">
                No pending connection requests right now.
              </div>
            ) : (
              <div className="space-y-3">
                {pendingIncoming.map((req) => (
                  <div key={req.id} className="p-4 rounded-xl bg-space-850/60 border border-amber-500/20 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <span className="text-xl p-1.5 rounded-lg bg-space-800 border border-white/[0.06]">
                          {req.from_avatar}
                        </span>
                        <div>
                          <span className="font-semibold text-white text-sm">{req.from_name}</span>
                          <p className="text-[10px] font-mono text-universe-slate">
                            Topic: <strong className="text-amber-300">{req.topic}</strong>
                          </p>
                        </div>
                      </div>
                      <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 text-[10px] font-mono">
                        PENDING CONSENT
                      </span>
                    </div>

                    <p className="text-xs text-universe-text font-sans bg-space-900/60 p-3 rounded-lg border border-white/[0.05]">
                      "{req.message}"
                    </p>

                    <div className="flex items-center justify-end gap-2 pt-1">
                      <button
                        onClick={() => handleRespondToRequest(req.id, false)}
                        className="px-3 py-1.5 rounded-xl border border-white/[0.1] hover:bg-space-800 text-universe-slate hover:text-white text-xs transition-colors"
                      >
                        Decline
                      </button>
                      <button
                        onClick={() => handleRespondToRequest(req.id, true)}
                        className="px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(168,85,129,0.3)]"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Accept & Connect
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Active Partners */}
          <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-4">
            <h3 className="text-sm font-display font-semibold text-white flex items-center gap-2">
              <Heart className="w-4 h-4 text-purple-400" />
              Active Study Partners
            </h3>

            {acceptedConnections.length === 0 && sentRequests.size === 0 ? (
              <div className="p-5 rounded-xl bg-space-850/40 border border-white/[0.06] text-center text-xs text-universe-slate space-y-2">
                <Users className="w-6 h-6 mx-auto text-universe-slate/50" />
                <p>No active connections yet. Discover peers and send connection requests!</p>
              </div>
            ) : (
              <div className="space-y-2">
                {acceptedConnections.map((conn) => (
                  <div key={conn.id} className="p-4 rounded-xl bg-space-850/60 border border-emerald-500/20 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className="text-xl p-1.5 rounded-lg bg-space-800">{conn.from_avatar}</span>
                      <div>
                        <span className="font-semibold text-white text-sm">{conn.from_name}</span>
                        <p className="text-[10px] font-mono text-emerald-400">Connected • Topic: {conn.topic}</p>
                      </div>
                    </div>
                    <span className="px-3 py-1 rounded-lg bg-emerald-500/10 border border-emerald-400/30 text-emerald-300 text-xs font-mono">
                      Connected Partner
                    </span>
                  </div>
                ))}
                {[...sentRequests].map((peerId) => {
                  const peer = peers.find(p => p.learner_id === peerId);
                  if (!peer) return null;
                  return (
                    <div key={peerId} className="p-4 rounded-xl bg-space-850/60 border border-white/[0.06] flex items-center justify-between gap-3 opacity-75">
                      <div className="flex items-center gap-3">
                        <span className="text-xl p-1.5 rounded-lg bg-space-800">{peer.avatar_emoji}</span>
                        <div>
                          <span className="font-semibold text-white text-sm">{peer.display_name}</span>
                          <p className="text-[10px] font-mono text-amber-300">Request Pending — awaiting peer response</p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: MY PUBLIC PROFILE */}
      {activeTab === 'MY_PROFILE' && (
        <div className="space-y-5 animate-fade-in">
          <div className="p-6 rounded-2xl bg-space-900/70 border border-white/[0.08] space-y-5">
            <div className="flex items-center gap-4">
              <span className="text-3xl p-3 rounded-2xl bg-space-800 border border-white/[0.08]">👨‍🎓</span>
              <div>
                <h2 className="text-lg font-display font-bold text-white">
                  Learner ID // {learnerId}
                </h2>
                <p className="text-xs text-universe-slate font-mono">
                  Active Subject: {selectedSubject?.title || 'JEE STEM Curriculum'}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <h4 className="text-[11px] font-mono text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                  <Star className="w-3 h-3" />
                  Your Subject Strengths
                </h4>
                <p className="text-[10px] text-universe-slate">Concepts where your Bayesian mastery probability reaches proficiency.</p>
                <div className="flex flex-wrap gap-1.5">
                  {['Kinematics', 'Laws of Motion', 'Chemical Thermodynamics', 'Rotational Dynamics'].map(s => (
                    <span key={s} className="px-2.5 py-1 rounded-lg bg-emerald-950/40 border border-emerald-500/20 text-emerald-300 text-xs">
                      {s}
                    </span>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <h4 className="text-[11px] font-mono text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
                  <Target className="w-3 h-3" />
                  Your Active Learning Goals
                </h4>
                <p className="text-[10px] text-universe-slate">Concepts currently in your prioritized learning path.</p>
                <div className="flex flex-wrap gap-1.5">
                  {['Magnetic Effects of Current', 'Electrostatics', 'Integral Calculus'].map(g => (
                    <span key={g} className="px-2.5 py-1 rounded-lg bg-amber-950/30 border border-amber-500/20 text-amber-300 text-xs">
                      {g}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-space-850/40 border border-white/[0.06] text-xs text-universe-slate flex items-start gap-2.5">
              <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="text-white font-semibold">Privacy & Anonymity Controls</p>
                <p>
                  Your exact test results and diagnostic error logs are <strong className="text-emerald-300">strictly private</strong>. Only broad concept labels are shared with peers for matching.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
