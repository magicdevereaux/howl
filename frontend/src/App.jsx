import React, { useState, useEffect } from 'react';
import { API_URL, WS_URL } from './utils';
import ChatView from './components/ChatView';
import ReportModal from './components/ReportModal';
import DiscoverView from './components/DiscoverView';
import LegalPage from './components/LegalPage';
import LoginView from './components/LoginView';
import MatchesView from './components/MatchesView';
import PasswordReset from './components/PasswordReset';
import ProfileView from './components/ProfileView';
import RegisterView from './components/RegisterView';

export default function HowlApp() {
  // Read password-reset token from URL before any state is initialised.
  // e.g. https://howl.app?token=abc123  →  open reset-password view directly.
  const _urlResetToken = new URLSearchParams(window.location.search).get('token') || '';

  const [view, setView] = useState(
    // 'login' | 'register' | 'profile' | 'discover' | 'matches' | 'chat'
    // | 'forgot-password' | 'reset-password' | 'privacy' | 'terms'
    _urlResetToken ? 'reset-password' : 'login'
  );
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [age, setAge] = useState('');
  const [gender, setGender] = useState('');
  const [sexuality, setSexuality] = useState('');
  const [lookingFor, setLookingFor] = useState('');
  const [agePrefMin, setAgePrefMin] = useState('');
  const [agePrefMax, setAgePrefMax] = useState('');
  const [location, setLocation] = useState('');
  const [bio, setBio] = useState('');
  const [token, setToken] = useState(localStorage.getItem('access_token') || '');
  const [user, setUser] = useState(null);
  const [avatarStatus, setAvatarStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [generationStartTime, setGenerationStartTime] = useState(null);
  const [generationTime, setGenerationTime] = useState(null);
  const [discoverUsers, setDiscoverUsers] = useState([]);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState('');
  const [matches, setMatches] = useState([]);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [matchesError, setMatchesError] = useState('');
  const [matchPopup, setMatchPopup] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [blocksLoading, setBlocksLoading] = useState(false);
  const [swipeLoading, setSwipeLoading] = useState(false);
  const [swipeError, setSwipeError] = useState('');
  const [canUndo, setCanUndo] = useState(false);
  const [undoMessage, setUndoMessage] = useState('');
  const [currentMatch, setCurrentMatch] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState('');
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [messageInput, setMessageInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [reportModal, setReportModal] = useState(null); // null | { userId, name, messageId? }
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportError, setReportError] = useState('');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotDone, setForgotDone] = useState(false);
  const [resetToken, setResetToken] = useState(_urlResetToken);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetDone, setResetDone] = useState(false);
  const [resetError, setResetError] = useState('');

  // Derived state — must be declared before any useEffect that references them,
  // because const is in the TDZ until its declaration is reached. Rollup's
  // production bundler exposes this as "Cannot access '<minified>' before initialization".
  const STALE_PENDING_MS = 2 * 60 * 1000; // 2 minutes
  const isStale =
    avatarStatus?.avatar_status === 'pending' &&
    !!user?.bio &&
    (!avatarStatus?.avatar_status_updated_at ||
      Date.now() - new Date(avatarStatus.avatar_status_updated_at).getTime() > STALE_PENDING_MS);

  const isGenerating =
    (avatarStatus?.avatar_status === 'pending' || avatarStatus?.avatar_status === 'generating') &&
    !!user?.bio &&
    !isStale;

  useEffect(() => {
    if (token) {
      fetchProfile();
      fetchAvatarStatus();
      fetchMatches();
    }
  }, [token]);

  useEffect(() => {
    const shouldPoll =
      (avatarStatus?.avatar_status === 'pending' || avatarStatus?.avatar_status === 'generating') &&
      !!user?.bio &&
      !isStale;
    if (shouldPoll) {
      const interval = setInterval(fetchAvatarStatus, 3000);
      return () => clearInterval(interval);
    }
  }, [avatarStatus?.avatar_status, user?.bio, isStale]);

  // WebSocket connection for real-time chat delivery.
  // Replaces the previous 3-second polling approach.
  // Reconnects automatically after a 3-second backoff whenever the
  // connection drops (network glitch, server restart, etc.).
  useEffect(() => {
    if (view !== 'chat' || !currentMatch) return;

    const wsUrl = `${WS_URL}/api/matches/${currentMatch.id}/ws?token=${token}`;
    let ws = null;
    let reconnectTimer = null;
    let active = true; // false after cleanup so reconnect attempts stop

    const connect = () => {
      if (!active) return;
      ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const { type, message } = JSON.parse(event.data);
          if (type === 'new_message') {
            setMessages((prev) => {
              const byId = new Map(prev.map((m) => [m.id, m]));
              byId.set(message.id, message);
              return Array.from(byId.values()).sort((a, b) => a.id - b.id);
            });
          } else if (type === 'message_deleted') {
            setMessages((prev) => prev.map((m) => m.id === message.id ? message : m));
          }
        } catch { /* ignore malformed frames */ }
      };

      ws.onclose = () => {
        if (active) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        ws.close(); // triggers onclose → schedules reconnect
      };
    };

    connect();

    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [view, currentMatch?.id, token]);

  // Remove ?token= from the URL so the token isn't visible in browser history.
  useEffect(() => {
    if (_urlResetToken) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchProfile = async () => {
    try {
      const res = await fetch(`${API_URL}/api/profile/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        setName(data.name || '');
        setAge(data.age ? String(data.age) : '');
        setGender(data.gender || '');
        setSexuality(data.sexuality || '');
        setLookingFor(data.looking_for || '');
        setAgePrefMin(data.age_preference_min ? String(data.age_preference_min) : '');
        setAgePrefMax(data.age_preference_max ? String(data.age_preference_max) : '');
        setEmailNotifications(data.email_notifications ?? true);
        setLocation(data.location || '');
        setBio(data.bio || '');
        setView('profile');
      } else {
        setToken('');
        localStorage.removeItem('access_token');
      }
    } catch (err) {
      setError('Failed to fetch profile');
    }
  };

  const fetchAvatarStatus = async (currentToken) => {
    const authToken = currentToken !== undefined ? currentToken : token;
    try {
      const res = await fetch(`${API_URL}/api/avatar/status`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        setAvatarStatus(prev => {
          if (data.avatar_status === 'ready' && prev?.avatar_status !== 'ready') {
            setGenerationStartTime(t => {
              if (t !== null) {
                const elapsed = ((Date.now() - t) / 1000).toFixed(1);
                setGenerationTime(`${elapsed}s`);
              }
              return null;
            });
          }
          return data;
        });
      } else if (res.status === 401) {
        setToken('');
        localStorage.removeItem('access_token');
        setView('login');
        setError('Session expired. Please sign in again.');
      }
    } catch (err) {
      console.error('Failed to fetch avatar status', err);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (res.ok) {
        const newToken = data.access_token;
        setToken(newToken);
        localStorage.setItem('access_token', newToken);
        localStorage.setItem('refresh_token', data.refresh_token);
        setUser(data.user);
        setName(data.user.name || '');
        setLocation(data.user.location || '');
        setBio(data.user.bio || '');
        setView('profile');
        fetchAvatarStatus(newToken);
      } else {
        setError(data.detail || 'Login failed');
      }
    } catch (err) {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (res.ok) {
        setToken(data.access_token);
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        setUser(data.user);
        setName(data.user.name || '');
        setLocation(data.user.location || '');
        setBio(data.user.bio || '');
        setView('profile');
      } else {
        setError(data.detail || 'Registration failed');
      }
    } catch (err) {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateBio = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/profile/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          name: name || null,
          age: age ? parseInt(age, 10) : null,
          location: location || null,
          bio,
        })
      });
      const data = await res.json();
      if (res.ok) {
        setUser(data);
        setName(data.name || '');
        setAge(data.age ? String(data.age) : '');
        setGender(data.gender || '');
        setSexuality(data.sexuality || '');
        setLookingFor(data.looking_for || '');
        setAgePrefMin(data.age_preference_min ? String(data.age_preference_min) : '');
        setAgePrefMax(data.age_preference_max ? String(data.age_preference_max) : '');
        setEmailNotifications(data.email_notifications ?? true);
        setLocation(data.location || '');
        setGenerationStartTime(Date.now());
        setGenerationTime(null);
        setAvatarStatus({ avatar_status: 'generating', animal: null });
        setTimeout(fetchAvatarStatus, 2000);
      } else {
        setError(data.detail || 'Update failed');
      }
    } catch (err) {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    const refreshToken = localStorage.getItem('refresh_token');
    if (refreshToken) {
      fetch(`${API_URL}/api/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => {}); // fire-and-forget — local state is always cleared
    }
    setToken('');
    setUser(null);
    setAvatarStatus(null);
    setEmail('');
    setPassword('');
    setName('');
    setAge('');
    setGender('');
    setSexuality('');
    setLookingFor('');
    setAgePrefMin('');
    setAgePrefMax('');
    setLocation('');
    setBio('');
    setDiscoverUsers([]);
    setMatches([]);
    setMatchPopup(null);
    setCurrentMatch(null);
    setMessages([]);
    setMessageInput('');
    setMatchesError('');
    setMessagesError('');
    setSendError('');
    setSwipeError('');
    setView('login');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  };

  const handleDeleteAccount = async () => {
    setDeleteLoading(true);
    setDeleteError('');
    try {
      const res = await fetch(`${API_URL}/api/profile/me`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 204) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        setToken('');
        setUser(null);
        setAvatarStatus(null);
        setEmail('');
        setPassword('');
        setName('');
        setLocation('');
        setBio('');
        setDiscoverUsers([]);
        setMatches([]);
        setMessages([]);
        setCurrentMatch(null);
        setDeleteModalOpen(false);
        setDeleteConfirmText('');
        setView('register');
      } else {
        const data = await res.json().catch(() => ({}));
        setDeleteError(data.detail || 'Deletion failed — please try again.');
      }
    } catch {
      setDeleteError('Network error — please try again.');
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleForgotPassword = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await fetch(`${API_URL}/api/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: forgotEmail }),
      });
      setForgotDone(true);
    } catch {
      setError('Network error — please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    setResetError('');
    if (newPassword !== confirmPassword) {
      setResetError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: resetToken, new_password: newPassword }),
      });
      if (res.ok) {
        setResetDone(true);
        setNewPassword('');
        setConfirmPassword('');
      } else {
        const data = await res.json().catch(() => ({}));
        setResetError(data.detail || 'Reset failed — the link may have expired.');
      }
    } catch {
      setResetError('Network error — please try again.');
    } finally {
      setLoading(false);
    }
  };

  const loadMessages = async (matchId) => {
    setMessagesLoading(true);
    setMessagesError('');
    try {
      const res = await fetch(`${API_URL}/api/matches/${matchId}/messages`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages);
        setHasMoreMessages(data.has_more);
      } else {
        setMessagesError("Couldn't load messages.");
      }
    } catch {
      setMessagesError('Network error — check your connection.');
    } finally {
      setMessagesLoading(false);
    }
  };

  const handleDeleteMessage = async (messageId) => {
    if (!currentMatch) return;
    try {
      const res = await fetch(
        `${API_URL}/api/matches/${currentMatch.id}/messages/${messageId}`,
        { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } },
      );
      if (res.ok) {
        const updated = await res.json();
        setMessages((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      }
    } catch { /* ignore */ }
  };

  const loadMoreMessages = async () => {
    if (!currentMatch || loadingMore || !hasMoreMessages || messages.length === 0) return;
    setLoadingMore(true);
    try {
      const oldestId = Math.min(...messages.map((m) => m.id));
      const res = await fetch(
        `${API_URL}/api/matches/${currentMatch.id}/messages?before_id=${oldestId}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (res.ok) {
        const data = await res.json();
        setMessages((prev) => [...data.messages, ...prev]);
        setHasMoreMessages(data.has_more);
      }
    } catch { /* ignore */ }
    finally { setLoadingMore(false); }
  };

  const sendMessage = async () => {
    const content = messageInput.trim();
    if (!content || !currentMatch || sending) return;
    setSending(true);
    setSendError('');
    setMessageInput('');
    try {
      const res = await fetch(`${API_URL}/api/matches/${currentMatch.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ content }),
      });
      if (res.ok) {
        const msg = await res.json();
        setMessages(prev => [...prev, msg]);
      } else {
        setMessageInput(content);
        setSendError("Message failed to send — please try again.");
      }
    } catch {
      setMessageInput(content);
      setSendError('Network error — message not sent.');
    } finally {
      setSending(false);
    }
  };

  const openChat = (match) => {
    setCurrentMatch(match);
    setMessages([]);
    setMessagesError('');
    setSendError('');
    setView('chat');
    loadMessages(match.id);
  };

  const fetchBlocks = async () => {
    setBlocksLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/blocks`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setBlocks(await res.json());
    } catch { /* ignore */ }
    finally { setBlocksLoading(false); }
  };

  const handleUnmatch = async (matchId) => {
    await fetch(`${API_URL}/api/matches/${matchId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    setCurrentMatch(null);
    setMessages([]);
    setView('matches');
    fetchMatches();
  };

  const handleBlockAndReport = async (userId, reason, notes) => {
    await handleBlock(userId); // navigate away and reload matches
    try {
      await fetch(`${API_URL}/api/reports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          reported_user_id: userId,
          reason,
          ...(notes ? { notes } : {}),
        }),
      });
    } catch { /* block succeeded — report failure is non-critical */ }
  };

  const handleBlock = async (userId) => {
    await fetch(`${API_URL}/api/blocks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ blocked_id: userId }),
    });
    // Remove from discover stack if present
    setDiscoverUsers(prev => prev.filter(u => u.id !== userId));
    // If blocking from chat, go back to matches
    if (currentMatch?.other_user?.id === userId) {
      setCurrentMatch(null);
      setMessages([]);
      setView('matches');
      fetchMatches();
    }
    fetchBlocks();
  };

  const handleUnblock = async (userId) => {
    await fetch(`${API_URL}/api/blocks/${userId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    setBlocks(prev => prev.filter(b => b.id !== userId));
  };

  const handleRegenerate = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/avatar/regenerate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (res.ok) {
        setGenerationStartTime(Date.now());
        setGenerationTime(null);
        setAvatarStatus(data);
      } else {
        setError(data.detail || 'Regeneration failed');
      }
    } catch (err) {
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  const handleCopyAnimal = () => {
    if (!avatarStatus?.animal) return;
    navigator.clipboard.writeText(avatarStatus.animal).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleOpenReport = (userId, name, messageId = undefined) => {
    setReportError('');
    setReportModal({ userId, name, messageId });
  };

  const handleSubmitReport = async (reason, notes) => {
    setReportSubmitting(true);
    setReportError('');
    try {
      const body = {
        reported_user_id: reportModal.userId,
        reason,
        ...(notes ? { notes } : {}),
        ...(reportModal.messageId != null ? { message_id: reportModal.messageId } : {}),
      };
      const res = await fetch(`${API_URL}/api/reports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setReportModal(null);
      } else {
        const data = await res.json().catch(() => ({}));
        setReportError(data.detail || 'Submission failed — please try again.');
      }
    } catch {
      setReportError('Network error — please try again.');
    } finally {
      setReportSubmitting(false);
    }
  };

  const handleSaveFilters = async ({ lookingFor: lf, gender: g, sexuality: s, agePrefMin: amin, agePrefMax: amax }) => {
    setLookingFor(lf);
    setGender(g);
    setSexuality(s);
    setAgePrefMin(amin);
    setAgePrefMax(amax);
    try {
      await fetch(`${API_URL}/api/profile/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          looking_for: lf || null,
          gender: g || null,
          sexuality: s || null,
          age_preference_min: amin ? parseInt(amin, 10) : null,
          age_preference_max: amax ? parseInt(amax, 10) : null,
        }),
      });
    } catch { /* ignore */ }
    fetchDiscoverUsers();
  };

  const handleToggleNotifications = async (enabled) => {
    setEmailNotifications(enabled);
    try {
      await fetch(`${API_URL}/api/profile/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ email_notifications: enabled }),
      });
    } catch { /* silently revert on network error */ }
  };

  const fetchDiscoverUsers = async () => {
    setDiscoverLoading(true);
    setDiscoverError('');
    try {
      const res = await fetch(`${API_URL}/api/users/discover`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setDiscoverUsers(await res.json());
      } else if (res.status === 401) {
        setToken('');
        localStorage.removeItem('access_token');
        setView('login');
        setError('Session expired. Please sign in again.');
      } else {
        setDiscoverError('Failed to load users');
      }
    } catch {
      setDiscoverError('Network error');
    } finally {
      setDiscoverLoading(false);
    }
  };

  const fetchMatches = async () => {
    setMatchesLoading(true);
    setMatchesError('');
    try {
      const res = await fetch(`${API_URL}/api/users/matches`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setMatches(await res.json());
      } else if (res.status === 401) {
        setToken('');
        localStorage.removeItem('access_token');
        setView('login');
        setError('Session expired. Please sign in again.');
      } else {
        setMatchesError("Couldn't load your matches.");
      }
    } catch {
      setMatchesError('Network error — check your connection.');
    } finally {
      setMatchesLoading(false);
    }
  };

  const handleSwipe = async (targetUserId, direction) => {
    setSwipeLoading(true);
    setUndoMessage('');
    setSwipeError('');
    try {
      const res = await fetch(`${API_URL}/api/swipes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ target_user_id: targetUserId, direction }),
      });
      const data = await res.json();
      setDiscoverUsers(prev => prev.slice(1));
      setCanUndo(true);
      if (res.ok && data.matched) {
        setMatchPopup(data.match);
      } else if (!res.ok) {
        setSwipeError('Swipe failed — tap to try again.');
        setTimeout(() => setSwipeError(''), 4000);
      }
    } catch {
      setDiscoverUsers(prev => prev.slice(1));
      setSwipeError('Network error — swipe may not have saved.');
      setTimeout(() => setSwipeError(''), 4000);
    } finally {
      setSwipeLoading(false);
    }
  };

  const handleUndo = async () => {
    setSwipeLoading(true);
    setUndoMessage('');
    try {
      const res = await fetch(`${API_URL}/api/swipes/last`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setDiscoverUsers(prev => [data.user, ...prev]);
        setCanUndo(false);
        const name = data.user.name || 'that person';
        setUndoMessage(`↩️ Undid swipe on ${name}`);
        setTimeout(() => setUndoMessage(''), 3000);
      } else if (res.status === 404) {
        setCanUndo(false);
      }
    } catch {
      // ignore network errors silently
    } finally {
      setSwipeLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Routing
  // ---------------------------------------------------------------------------

  // Declared here — before any conditional returns — to avoid the TDZ.
  // const bindings are in the temporal dead zone until their declaration
  // is reached, so any early return above this point would throw if it
  // referenced reportModalEl.
  const reportModalEl = (
    <ReportModal
      target={reportModal ? { name: reportModal.name, messageId: reportModal.messageId } : null}
      onClose={() => setReportModal(null)}
      onSubmit={handleSubmitReport}
      submitting={reportSubmitting}
      error={reportError}
    />
  );

  const totalUnread = matches.reduce((sum, m) => sum + (m.unread_count || 0), 0);
  const navProps = { view, setView, fetchDiscoverUsers, fetchMatches, handleLogout, totalUnread };

  if (view === 'privacy' || view === 'terms') {
    return <LegalPage view={view} setView={setView} />;
  }

  if (view === 'forgot-password' || view === 'reset-password') {
    return (
      <PasswordReset
        view={view} setView={setView}
        forgotEmail={forgotEmail} setForgotEmail={setForgotEmail}
        forgotDone={forgotDone} error={error} loading={loading}
        handleForgotPassword={handleForgotPassword}
        resetToken={resetToken} setResetToken={setResetToken}
        newPassword={newPassword} setNewPassword={setNewPassword}
        confirmPassword={confirmPassword} setConfirmPassword={setConfirmPassword}
        resetDone={resetDone} setResetDone={setResetDone}
        resetError={resetError} handleResetPassword={handleResetPassword}
      />
    );
  }

  if (view === 'register') {
    return (
      <RegisterView
        email={email} setEmail={setEmail}
        password={password} setPassword={setPassword}
        error={error} loading={loading}
        handleRegister={handleRegister} setView={setView}
      />
    );
  }

  if (view === 'login') {
    return (
      <LoginView
        email={email} setEmail={setEmail}
        password={password} setPassword={setPassword}
        error={error} loading={loading}
        handleLogin={handleLogin} setView={setView}
        setForgotEmail={setForgotEmail}
        setForgotDone={setForgotDone}
        setError={setError}
      />
    );
  }

  if (view === 'discover') {
    return (
      <>
        <DiscoverView
          discoverUsers={discoverUsers}
          discoverLoading={discoverLoading}
          discoverError={discoverError}
          swipeLoading={swipeLoading}
          swipeError={swipeError}
          canUndo={canUndo}
          undoMessage={undoMessage}
          matchPopup={matchPopup}
          setMatchPopup={setMatchPopup}
          avatarStatus={avatarStatus}
          preferenceFilters={{ lookingFor, gender, sexuality, agePrefMin, agePrefMax }}
          handleSaveFilters={handleSaveFilters}
          handleSwipe={handleSwipe}
          handleUndo={handleUndo}
          handleBlock={handleBlock}
          handleOpenReport={handleOpenReport}
          fetchDiscoverUsers={fetchDiscoverUsers}
          setView={setView}
          fetchMatches={fetchMatches}
          navProps={navProps}
        />
        {reportModalEl}
      </>
    );
  }

  if (view === 'matches') {
    return (
      <>
        <MatchesView
          matches={matches}
          matchesLoading={matchesLoading}
          matchesError={matchesError}
          fetchMatches={fetchMatches}
          openChat={openChat}
          user={user}
          setView={setView}
          fetchDiscoverUsers={fetchDiscoverUsers}
          handleOpenReport={handleOpenReport}
          navProps={navProps}
        />
        {reportModalEl}
      </>
    );
  }

  if (view === 'chat' && currentMatch) {
    return (
      <>
        <ChatView
          currentMatch={currentMatch}
          messages={messages}
          setMessages={setMessages}
          messagesLoading={messagesLoading}
          messagesError={messagesError}
          messageInput={messageInput}
          setMessageInput={setMessageInput}
          sending={sending}
          sendError={sendError}
          sendMessage={sendMessage}
          loadMessages={loadMessages}
          hasMoreMessages={hasMoreMessages}
          loadingMore={loadingMore}
          loadMoreMessages={loadMoreMessages}
          handleDeleteMessage={handleDeleteMessage}
          handleUnmatch={handleUnmatch}
          handleBlock={handleBlock}
          handleBlockAndReport={handleBlockAndReport}
          handleOpenReport={handleOpenReport}
          setView={setView}
          fetchMatches={fetchMatches}
        />
        {reportModalEl}
      </>
    );
  }

  // Default: profile view
  return (
    <>
      <ProfileView
        user={user}
        avatarStatus={avatarStatus}
        generationTime={generationTime}
        isStale={isStale}
        isGenerating={isGenerating}
        name={name} setName={setName}
        age={age} setAge={setAge}
        location={location} setLocation={setLocation}
        bio={bio} setBio={setBio}
        error={error}
        loading={loading}
        copied={copied}
        handleUpdateBio={handleUpdateBio}
        handleRegenerate={handleRegenerate}
        handleCopyAnimal={handleCopyAnimal}
        deleteModalOpen={deleteModalOpen}
        setDeleteModalOpen={setDeleteModalOpen}
        deleteConfirmText={deleteConfirmText}
        setDeleteConfirmText={setDeleteConfirmText}
        deleteLoading={deleteLoading}
        deleteError={deleteError}
        setDeleteError={setDeleteError}
        handleDeleteAccount={handleDeleteAccount}
        emailNotifications={emailNotifications}
        handleToggleNotifications={handleToggleNotifications}
        blocks={blocks}
        blocksLoading={blocksLoading}
        fetchBlocks={fetchBlocks}
        handleUnblock={handleUnblock}
        navProps={navProps}
      />
      {reportModalEl}
    </>
  );
}
