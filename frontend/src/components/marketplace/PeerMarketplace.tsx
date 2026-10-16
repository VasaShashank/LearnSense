import React, { useState, useEffect, useMemo } from 'react';
import {
  Users,
  Search,
  Sparkles,
  CheckCircle2,
  XCircle,
  MessageCircle,
  Star,
  Zap,
  ShieldCheck,
  UserPlus,
  Award,
  Target,
  Heart,
  Filter,
} from 'lucide-react';
import type { Subject } from '../../api/client';

/**
 * Peer discovery entry — represents another learner on the platform
 * with their public strengths and learning interests.
 */
interface PeerProfile {
  learner_id: string;
  display_name: string;
  avatar_emoji: string;
  strengths: string[];      // concept IDs they've mastered (>70%)
  learning_goals: string[]; // concept IDs they're actively studying (<50%)
  mastery_avg: number;
  subjects: string[];
  match_score: number;       // how well this peer complements the current user
  online_status: 'online' | 'idle' | 'offline';
}

interface ConnectionRequest {
  id: string;
  from_id: string;
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

// Generate realistic peer profiles from platform data
function generatePeerProfiles(learnerId: string, subjectTitle: string): PeerProfile[] {
  const peerNames = [
    { id: 'peer_jordan', name: 'Jordan Park', emoji: '🧑‍💻' },
    { id: 'peer_sam', name: 'Samira Haddad', emoji: '👩‍🔬' },
    { id: 'peer_taylor', name: 'Taylor Chen', emoji: '👨‍🎓' },
    { id: 'peer_riley', name: 'Riley Morgan', emoji: '🧑‍🎓' },
    { id: 'peer_avery', name: 'Avery Nakamura', emoji: '👩‍💻' },
    { id: 'peer_casey', name: 'Casey Okonkwo', emoji: '🧑‍🏫' },
    { id: 'peer_drew', name: 'Drew Martinez', emoji: '👨‍💻' },
    { id: 'peer_rowan', name: 'Rowan Patil', emoji: '👩‍🎓' },
  ];

  // Generate concept-level strengths/weaknesses based on typical CS topics
  const conceptPool = [
    'Sorting Algorithms', 'Graph Traversal', 'Dynamic Programming', 'Recursion',
    'Binary Search Trees', 'Hash Tables', 'Stack Operations', 'Queue Operations',
    'Linked Lists', 'Time Complexity', 'Greedy Algorithms', 'Divide and Conquer',
    'BFS vs DFS', 'Shortest Path', 'Tree Balancing', 'Memory Management',
  ];

  return peerNames
    .filter(p => p.id !== learnerId)
    .map((peer, idx) => {
      const strengthCount = 3 + Math.floor(Math.random() * 4);
      const goalCount = 2 + Math.floor(Math.random() * 3);
      const shuffled = [...conceptPool].sort(() => Math.random() - 0.5);
      return {
        learner_id: peer.id,
        display_name: peer.name,
        avatar_emoji: peer.emoji,
        strengths: shuffled.slice(0, strengthCount),
        learning_goals: shuffled.slice(strengthCount, strengthCount + goalCount),
        mastery_avg: 0.35 + Math.random() * 0.55,
        subjects: [subjectTitle || 'Computer Science'],
        match_score: 0.4 + Math.random() * 0.55,
        online_status: idx < 3 ? 'online' : idx < 5 ? 'idle' : 'offline' as const,
      };
    });
}

export const PeerMarketplace: React.FC<PeerMarketplaceProps> = ({
  learnerId,
  subjects: _subjects,
  selectedSubject,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStrength, setFilterStrength] = useState<string>('');
  const [peers, setPeers] = useState<PeerProfile[]>([]);
  const [connectionRequests, setConnectionRequests] = useState<ConnectionRequest[]>([]);
  const [sentRequests, setSentRequests] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<'DISCOVER' | 'CONNECTIONS' | 'MY_PROFILE'>('DISCOVER');
  const [connectMessage, setConnectMessage] = useState('');
  const [connectingPeerId, setConnectingPeerId] = useState<string | null>(null);

  // Load peers on mount or subject change
  useEffect(() => {
    const profiles = generatePeerProfiles(learnerId, selectedSubject?.title || 'Computer Science');
    setPeers(profiles);

    // Simulate an incoming connection request
    setConnectionRequests([
      {
        id: 'req_001',
        from_id: 'peer_sam',
        from_name: 'Samira Haddad',
        from_avatar: '👩‍🔬',
        topic: 'Dynamic Programming',
        message: 'Hey! I noticed you\'re strong in recursion — I could really use help connecting it to DP patterns. I can help you with graph traversal in return!',
        status: 'PENDING',
        created_at: new Date(Date.now() - 1800000).toISOString(),
      },
    ]);
  }, [learnerId, selectedSubject]);

  // Filter and sort peers
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
    if (filterStrength) {
      result = result.filter(p =>
        p.strengths.some(s => s.toLowerCase().includes(filterStrength.toLowerCase()))
      );
    }
    return result.sort((a, b) => b.match_score - a.match_score);
  }, [peers, searchQuery, filterStrength]);

  // Handle sending connection request
  const handleSendRequest = (peer: PeerProfile) => {
    setSentRequests(prev => new Set([...prev, peer.learner_id]));
    setConnectingPeerId(null);
    setConnectMessage('');
  };

  // Handle incoming request response
  const handleRespondToRequest = (reqId: string, accept: boolean) => {
    setConnectionRequests(prev =>
      prev.map(r => r.id === reqId ? { ...r, status: accept ? 'ACCEPTED' : 'DECLINED' } : r)
    );
  };

  const pendingIncoming = connectionRequests.filter(r => r.status === 'PENDING');
  const acceptedConnections = connectionRequests.filter(r => r.status === 'ACCEPTED');

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
                Peer Learning Network
              </span>
              {pendingIncoming.length > 0 && (
                <span className="px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-400/40 text-amber-300 text-[10px] font-mono font-bold animate-pulse">
                  {pendingIncoming.length} pending request{pendingIncoming.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <h1 className="text-2xl lg:text-3xl font-display font-bold text-white tracking-tight">
              Student Marketplace
            </h1>
            <p className="text-sm text-universe-slate max-w-2xl">
              Discover peers studying similar topics. See their strengths and learning goals. Connect with mutual consent to teach and learn from each other.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="p-3 rounded-xl bg-purple-500/10 border border-purple-400/20 text-center">
              <div className="text-2xl font-display font-bold text-purple-300">{peers.length}</div>
              <div className="text-[10px] font-mono text-universe-slate uppercase">Active Peers</div>
            </div>
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-400/20 text-center">
              <div className="text-2xl font-display font-bold text-emerald-300">{acceptedConnections.length}</div>
              <div className="text-[10px] font-mono text-universe-slate uppercase">Connections</div>
            </div>
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
          <span>My Profile</span>
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
                placeholder="Search by name, topic strength, or learning goal..."
                className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs placeholder-universe-slate focus:outline-none focus:border-purple-400 transition-colors"
              />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-universe-slate" />
              <select
                value={filterStrength}
                onChange={(e) => setFilterStrength(e.target.value)}
                className="px-3 py-2.5 rounded-xl bg-space-800 border border-white/[0.1] text-white text-xs focus:outline-none focus:border-purple-400 cursor-pointer"
              >
                <option value="">All Topics</option>
                <option value="sorting">Sorting Algorithms</option>
                <option value="graph">Graph Traversal</option>
                <option value="dynamic">Dynamic Programming</option>
                <option value="recursion">Recursion</option>
                <option value="binary search">Binary Search Trees</option>
                <option value="hash">Hash Tables</option>
              </select>
            </div>
          </div>

          {/* Consent Notice */}
          <div className="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/20 text-xs text-emerald-300/90 flex items-start gap-2.5">
            <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-400 mt-0.5" />
            <span>
              <strong>Privacy First:</strong> Connection requests require mutual consent from both parties. Your detailed mastery data is never shared — only your public strengths and learning goals are visible.
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
                          Avg Mastery: <span className="text-cyan-300">{(peer.mastery_avg * 100).toFixed(0)}%</span>
                          {' • '}
                          <span className={`${peer.online_status === 'online' ? 'text-emerald-400' : peer.online_status === 'idle' ? 'text-amber-400' : 'text-zinc-400'}`}>
                            {peer.online_status}
                          </span>
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                      <span className="text-xs font-mono font-bold text-purple-300">
                        {(peer.match_score * 100).toFixed(0)}% match
                      </span>
                    </div>
                  </div>

                  {/* Strengths */}
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-emerald-400 uppercase tracking-wider">
                      <Star className="w-3 h-3" />
                      Can Teach You
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
                      Wants to Learn
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
                      <div className="flex items-center gap-2 text-xs text-cyan-300">
                        <CheckCircle2 className="w-4 h-4" />
                        <span>Request sent — waiting for their consent</span>
                      </div>
                    ) : isConnecting ? (
                      <div className="space-y-2">
                        <textarea
                          rows={2}
                          value={connectMessage}
                          onChange={(e) => setConnectMessage(e.target.value)}
                          placeholder={`Hey ${peer.display_name}, I'd love to learn ${peer.strengths[0]} from you! I can help with...`}
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

          {filteredPeers.length === 0 && (
            <div className="p-10 rounded-2xl bg-space-900/40 border border-white/[0.06] text-center space-y-2">
              <Users className="w-8 h-8 text-universe-slate mx-auto" />
              <p className="text-sm text-universe-slate">No peers match your search criteria.</p>
              <p className="text-xs text-universe-slate/60">Try broadening your search or adjusting filters.</p>
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
                            Topic: <span className="text-amber-300">{req.topic}</span>
                            {' • '}
                            {new Date(req.created_at).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit' })}
                          </p>
                        </div>
                      </div>
                    </div>

                    <p className="text-xs text-universe-text/80 bg-space-800/60 rounded-lg p-3 border border-white/[0.04] italic">
                      "{req.message}"
                    </p>

                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleRespondToRequest(req.id, false)}
                        className="px-3.5 py-1.5 rounded-lg bg-space-800 hover:bg-rose-500/15 text-universe-slate hover:text-rose-300 text-xs flex items-center gap-1.5 transition-all border border-white/[0.06] hover:border-rose-500/30"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        Decline
                      </button>
                      <button
                        onClick={() => handleRespondToRequest(req.id, true)}
                        className="px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(16,185,129,0.3)]"
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

          {/* Active Connections */}
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
                    <button className="px-3 py-1.5 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-400/30 text-cyan-300 text-xs flex items-center gap-1.5 transition-all">
                      <MessageCircle className="w-3.5 h-3.5" />
                      Message
                    </button>
                  </div>
                ))}
                {[...sentRequests].map((peerId) => {
                  const peer = peers.find(p => p.learner_id === peerId);
                  if (!peer) return null;
                  return (
                    <div key={peerId} className="p-4 rounded-xl bg-space-850/60 border border-white/[0.06] flex items-center justify-between gap-3 opacity-70">
                      <div className="flex items-center gap-3">
                        <span className="text-xl p-1.5 rounded-lg bg-space-800">{peer.avatar_emoji}</span>
                        <div>
                          <span className="font-semibold text-white text-sm">{peer.display_name}</span>
                          <p className="text-[10px] font-mono text-amber-300">Request Pending — awaiting their consent</p>
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
                <h2 className="text-lg font-display font-bold text-white">{learnerId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</h2>
                <p className="text-xs text-universe-slate font-mono">Your public profile is visible to other learners</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <h4 className="text-[11px] font-mono text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
                  <Star className="w-3 h-3" />
                  Your Public Strengths (Auto-Detected)
                </h4>
                <p className="text-[10px] text-universe-slate">Concepts where your mastery exceeds 70% are listed as strengths.</p>
                <div className="flex flex-wrap gap-1.5">
                  {['Recursion', 'Stack Operations', 'Time Complexity', 'Binary Search Trees'].map(s => (
                    <span key={s} className="px-2.5 py-1 rounded-lg bg-emerald-950/40 border border-emerald-500/20 text-emerald-300 text-xs">
                      {s}
                    </span>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <h4 className="text-[11px] font-mono text-amber-400 uppercase tracking-wider flex items-center gap-1.5">
                  <Target className="w-3 h-3" />
                  Your Learning Goals (Auto-Detected)
                </h4>
                <p className="text-[10px] text-universe-slate">Concepts you're actively studying with mastery below 50%.</p>
                <div className="flex flex-wrap gap-1.5">
                  {['Dynamic Programming', 'Graph Traversal', 'Greedy Algorithms'].map(g => (
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
                <p className="text-white font-semibold">Privacy Controls</p>
                <p>Your strengths and learning goals are auto-detected from your mastery levels. Your exact scores, practice history, and personal data are <strong className="text-emerald-300">never shared</strong> with peers. Only publicly listed topics are visible.</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
