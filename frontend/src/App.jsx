import React, { useState, useEffect, useRef } from 'react';

export default function HowlApp() {
  // Read password-reset token from URL before any state is initialised.
  // e.g. https://howl.app?token=abc123  →  open reset-password view directly.
  const _urlResetToken = new URLSearchParams(window.location.search).get('token') || '';

  const [view, setView] = useState(
    // 'login' | 'register' | 'profile' | 'discover' | 'matches' | 'chat'
    // | 'forgot-password' | 'reset-password'
    _urlResetToken ? 'reset-password' : 'login'
  );
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [age, setAge] = useState('');
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
  const [matchPopup, setMatchPopup] = useState(null); // null | match object
  const [swipeLoading, setSwipeLoading] = useState(false);
  const [swipeError, setSwipeError] = useState('');
  const [canUndo, setCanUndo] = useState(false);
  const [undoMessage, setUndoMessage] = useState('');
  const [currentMatch, setCurrentMatch] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState('');
  const [messageInput, setMessageInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
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

  const messagesEndRef = useRef(null);

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';

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

  // Poll for new messages every 3 s while the chat view is open.
  useEffect(() => {
    if (view !== 'chat' || !currentMatch) return;
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/api/matches/${currentMatch.id}/messages`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) setMessages(await res.json());
      } catch { /* ignore */ }
    };
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [view, currentMatch?.id, token]);

  // Scroll to the latest message whenever the messages array changes.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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
        body: JSON.stringify({ name: name || null, age: age ? parseInt(age, 10) : null, location: location || null, bio })
      });
      const data = await res.json();
      if (res.ok) {
        setUser(data);
        setName(data.name || '');
        setAge(data.age ? String(data.age) : '');
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
    setToken('');
    setUser(null);
    setAvatarStatus(null);
    setEmail('');
    setPassword('');
    setName('');
    setAge('');
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
        // Wipe all local state then go to register so they can start fresh
        localStorage.removeItem('access_token');
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

  // Remove ?token= from the URL so the token isn't visible in browser history.
  useEffect(() => {
    if (_urlResetToken) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
      // Always show success — don't leak whether the email exists
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
        setMessages(await res.json());
      } else {
        setMessagesError("Couldn't load messages.");
      }
    } catch {
      setMessagesError('Network error — check your connection.');
    } finally {
      setMessagesLoading(false);
    }
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
        // Push the restored user back to the front of the stack
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

  const getStatusEmoji = () => {
    if (!user?.bio) return <span>🐺</span>;
    if (!avatarStatus) return <span>🐺</span>;
    if (isStale) return <span>⚠️</span>;
    switch (avatarStatus.avatar_status) {
      case 'ready': return <span>✨</span>;
      case 'generating':
      case 'pending': return <span className="spinner">⏳</span>;
      case 'failed': return <span>❌</span>;
      default: return <span>🐺</span>;
    }
  };

  const getStatusText = () => {
    if (!user?.bio) return 'Fill in your bio to discover your spirit animal';
    if (!avatarStatus) return 'No avatar yet';
    if (isStale) return 'Generation timed out — click Try Again below';
    switch (avatarStatus.avatar_status) {
      case 'ready': return `Your spirit animal: ${avatarStatus.animal}`;
      case 'generating':
      case 'pending': return 'Claude is analyzing your bio...';
      case 'failed': return 'Avatar generation failed — try updating your bio';
      default: return 'Unknown status';
    }
  };

  const ANIMAL_EMOJI = {
    wolf: '🐺', fox: '🦊', deer: '🦌', bear: '🐻', owl: '🦉',
    cat: '🐱', lion: '🦁', otter: '🦦', eagle: '🦅', panther: '🐆',
    hawk: '🦅', rabbit: '🐰', dolphin: '🐬', crow: '🐦‍⬛',
  };
  const animalEmoji = (animal) => ANIMAL_EMOJI[animal?.toLowerCase()] || '🐾';
  // Resolve avatar URL: stored paths are server-relative (/avatars/…), full URLs are used as-is.
  const avatarUrl = (url) => (!url ? null : url.startsWith('http') ? url : `${API_URL}${url}`);

  const navButton = (label, targetView, fetchFn) => {
    const active = view === targetView;
    return (
      <button
        onClick={() => { setView(targetView); fetchFn && fetchFn(); }}
        style={{
          padding: '10px 20px',
          background: active ? 'white' : 'rgba(255,255,255,0.15)',
          color: active ? '#667eea' : 'white',
          border: active ? 'none' : '1px solid rgba(255,255,255,0.3)',
          borderRadius: '8px',
          cursor: 'pointer',
          fontSize: '14px',
          fontWeight: active ? '600' : '500',
        }}
      >
        {label}
      </button>
    );
  };

  const Nav = () => (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px', flexWrap: 'wrap', gap: '12px' }}>
      <h1 style={{ fontSize: '32px', fontWeight: '700', color: 'white' }}>Howl 🐺</h1>
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
        {navButton('Discover', 'discover', fetchDiscoverUsers)}
        {navButton('Matches ❤️', 'matches', fetchMatches)}
        {navButton('My Profile', 'profile', null)}
        <button
          onClick={handleLogout}
          style={{ padding: '10px 20px', background: 'rgba(255,255,255,0.15)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
        >
          Logout
        </button>
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Register view
  // ---------------------------------------------------------------------------
  if (view === 'register') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <h1 style={{ fontSize: '32px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Join Howl 🐺</h1>
          <p style={{ color: '#718096', marginBottom: '32px', textAlign: 'center' }}>Create your account</p>
          {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>{error}</div>}
          <form onSubmit={handleRegister}>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="wolf@howl.app" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
            </div>
            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
            </div>
            <button type="submit" disabled={loading} style={{ width: '100%', padding: '14px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}>
              {loading ? 'Creating account...' : 'Create Account'}
            </button>
          </form>
          <p style={{ marginTop: '24px', textAlign: 'center', color: '#718096', fontSize: '14px' }}>
            Already have an account?{' '}
            <button onClick={() => setView('login')} style={{ color: '#667eea', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>Sign in</button>
          </p>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Forgot-password view
  // ---------------------------------------------------------------------------
  if (view === 'forgot-password') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <h1 style={{ fontSize: '26px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Reset your password</h1>
          <p style={{ color: '#718096', marginBottom: '28px', textAlign: 'center', fontSize: '14px' }}>
            Enter your email and we'll send you a reset link.
          </p>

          {forgotDone ? (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>📬</div>
              <p style={{ color: '#2d3748', fontWeight: '600', marginBottom: '8px' }}>Check your server logs</p>
              <p style={{ color: '#718096', fontSize: '13px', marginBottom: '24px' }}>
                (Email delivery goes to console in dev mode — copy the link from there.)
              </p>
              <button onClick={() => setView('login')} style={{ color: '#667eea', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>
                Back to Sign In
              </button>
            </div>
          ) : (
            <>
              {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '16px', color: '#c53030', fontSize: '13px' }}>{error}</div>}
              <form onSubmit={handleForgotPassword}>
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Email</label>
                  <input type="email" value={forgotEmail} onChange={(e) => setForgotEmail(e.target.value)} placeholder="wolf@howl.app" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
                </div>
                <button type="submit" disabled={loading} style={{ width: '100%', padding: '14px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}>
                  {loading ? 'Sending…' : 'Send Reset Link'}
                </button>
              </form>
              <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
                <button onClick={() => setView('login')} style={{ color: '#718096', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
                  Back to Sign In
                </button>
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Reset-password view
  // ---------------------------------------------------------------------------
  if (view === 'reset-password') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <h1 style={{ fontSize: '26px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Set new password</h1>

          {resetDone ? (
            <div style={{ textAlign: 'center', marginTop: '16px' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>✅</div>
              <p style={{ color: '#2d3748', fontWeight: '600', marginBottom: '8px' }}>Password updated!</p>
              <p style={{ color: '#718096', fontSize: '13px', marginBottom: '24px' }}>You can now log in with your new password.</p>
              <button
                onClick={() => { setView('login'); setResetDone(false); setResetToken(''); }}
                style={{ padding: '12px 28px', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
              >
                Go to Sign In
              </button>
            </div>
          ) : (
            <>
              <p style={{ color: '#718096', marginBottom: '24px', textAlign: 'center', fontSize: '14px' }}>Choose a new password (8+ characters).</p>
              {resetError && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '16px', color: '#c53030', fontSize: '13px' }}>{resetError}</div>}
              <form onSubmit={handleResetPassword}>
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>New password</label>
                  <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="••••••••" required minLength={8} style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
                </div>
                <div style={{ marginBottom: '24px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Confirm password</label>
                  <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="••••••••" required minLength={8} style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
                </div>
                <button type="submit" disabled={loading || !newPassword || newPassword !== confirmPassword} style={{ width: '100%', padding: '14px', background: (loading || !newPassword || newPassword !== confirmPassword) ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: (loading || !newPassword || newPassword !== confirmPassword) ? 'not-allowed' : 'pointer' }}>
                  {loading ? 'Resetting…' : 'Reset Password'}
                </button>
              </form>
              <p style={{ marginTop: '20px', textAlign: 'center', fontSize: '14px' }}>
                <button onClick={() => setView('login')} style={{ color: '#718096', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
                  Back to Sign In
                </button>
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Login view
  // ---------------------------------------------------------------------------
  if (view === 'login') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <h1 style={{ fontSize: '32px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Welcome to Howl 🐺</h1>
          <p style={{ color: '#718096', marginBottom: '32px', textAlign: 'center' }}>Sign in to find your spirit animal</p>
          {error && <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>{error}</div>}
          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="wolf@howl.app" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
            </div>
            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
            </div>
            <button type="submit" disabled={loading} style={{ width: '100%', padding: '14px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer' }}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>
          <p style={{ marginTop: '16px', textAlign: 'center', fontSize: '14px' }}>
            <button onClick={() => { setView('forgot-password'); setForgotEmail(''); setForgotDone(false); setError(''); }} style={{ color: '#718096', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px' }}>
              Forgot password?
            </button>
          </p>
          <p style={{ marginTop: '8px', textAlign: 'center', color: '#718096', fontSize: '14px' }}>
            Don't have an account?{' '}
            <button onClick={() => setView('register')} style={{ color: '#667eea', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>Create one</button>
          </p>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Discover view (Tinder-style single card)
  // ---------------------------------------------------------------------------
  if (view === 'discover') {
    const currentCard = discoverUsers[0] || null;
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 20px' }}>
        <div style={{ maxWidth: '520px', margin: '0 auto' }}>
          <Nav />

          {discoverLoading ? (
            <div style={{ textAlign: 'center', color: 'white', padding: '60px', fontSize: '18px' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }} className="spinner">🐾</div>
              Finding spirit animals…
            </div>
          ) : discoverError ? (
            <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', color: '#c53030' }}>{discoverError}</div>
          ) : !currentCard ? (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.9)', padding: '60px', background: 'rgba(255,255,255,0.12)', borderRadius: '20px' }}>
              <div style={{ fontSize: '56px', marginBottom: '16px' }}>🎉</div>
              <p style={{ fontSize: '20px', fontWeight: '700' }}>You've seen everyone!</p>
              <p style={{ fontSize: '14px', marginTop: '8px', opacity: 0.8 }}>Check back later for new members.</p>
              <button
                onClick={fetchDiscoverUsers}
                style={{ marginTop: '20px', padding: '12px 28px', background: 'white', color: '#667eea', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '15px' }}
              >
                Refresh
              </button>
            </div>
          ) : (
            <>
              <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: '13px', marginBottom: '16px', textAlign: 'center' }}>
                {discoverUsers.length} {discoverUsers.length === 1 ? 'person' : 'people'} left
              </p>

              {/* Card */}
              <div style={{ background: 'white', borderRadius: '20px', overflow: 'hidden', boxShadow: '0 16px 48px rgba(0,0,0,0.25)' }}>
                <div style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 28px 28px', textAlign: 'center' }}>
                  {currentCard.avatar_url ? (
                    <img
                      src={avatarUrl(currentCard.avatar_url)}
                      alt={`${currentCard.name || 'User'}'s avatar`}
                      onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
                      style={{ width: '112px', height: '112px', borderRadius: '50%', objectFit: 'cover', marginBottom: '16px', border: '4px solid rgba(255,255,255,0.4)' }}
                    />
                  ) : null}
                  <div style={{ fontSize: '88px', lineHeight: 1, marginBottom: '16px', display: currentCard.avatar_url ? 'none' : 'block' }}>
                    {animalEmoji(currentCard.animal)}
                  </div>
                  <h2 style={{ color: 'white', fontSize: '26px', fontWeight: '700', margin: '0 0 4px' }}>
                    {currentCard.name || 'Anonymous'}
                  </h2>
                  <p style={{ color: 'rgba(255,255,255,0.9)', fontSize: '16px', margin: 0 }}>
                    {currentCard.animal ? currentCard.animal.charAt(0).toUpperCase() + currentCard.animal.slice(1) : ''}
                  </p>
                  {currentCard.location && (
                    <p style={{ color: 'rgba(255,255,255,0.75)', fontSize: '13px', marginTop: '8px' }}>
                      📍 {currentCard.location}
                    </p>
                  )}
                </div>

                <div style={{ padding: '24px 28px 28px' }}>
                  {currentCard.bio && (
                    <p style={{ color: '#4a5568', fontSize: '15px', lineHeight: '1.65', marginBottom: '16px' }}>
                      {currentCard.bio.length > 200 ? currentCard.bio.slice(0, 200).trimEnd() + '…' : currentCard.bio}
                    </p>
                  )}
                  {currentCard.personality_traits?.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '16px' }}>
                      {currentCard.personality_traits.map((trait, i) => (
                        <span key={i} style={{ background: '#eef2ff', color: '#667eea', padding: '4px 12px', borderRadius: '12px', fontSize: '13px', fontWeight: '500' }}>
                          {trait}
                        </span>
                      ))}
                    </div>
                  )}
                  {currentCard.avatar_description && (
                    <details style={{ marginBottom: '8px' }}>
                      <summary style={{ cursor: 'pointer', color: '#667eea', fontSize: '13px', fontWeight: '500', userSelect: 'none', listStyle: 'none' }}>
                        ✦ View spirit animal description
                      </summary>
                      <p style={{ marginTop: '10px', color: '#718096', fontSize: '13px', lineHeight: '1.6', padding: '10px 12px', background: '#f7fafc', borderRadius: '8px' }}>
                        {currentCard.avatar_description}
                      </p>
                    </details>
                  )}
                </div>
              </div>

              {/* Swipe buttons */}
              <div style={{ display: 'flex', justifyContent: 'center', gap: '24px', marginTop: '28px' }}>
                <button
                  disabled={swipeLoading}
                  onClick={() => handleSwipe(currentCard.id, 'pass')}
                  style={{ width: '72px', height: '72px', borderRadius: '50%', background: 'white', border: '2px solid #fed7d7', fontSize: '28px', cursor: swipeLoading ? 'not-allowed' : 'pointer', boxShadow: '0 4px 16px rgba(0,0,0,0.15)', transition: 'transform 0.15s, box-shadow 0.15s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1.1)')}
                  onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1)')}
                  title="Pass"
                >
                  ❌
                </button>
                <button
                  disabled={swipeLoading}
                  onClick={() => handleSwipe(currentCard.id, 'like')}
                  style={{ width: '72px', height: '72px', borderRadius: '50%', background: 'linear-gradient(135deg, #f687b3 0%, #ed64a6 100%)', border: 'none', fontSize: '28px', cursor: swipeLoading ? 'not-allowed' : 'pointer', boxShadow: '0 4px 16px rgba(237,100,166,0.4)', transition: 'transform 0.15s, box-shadow 0.15s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                  onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1.1)')}
                  onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.transform = 'scale(1)')}
                  title="Like"
                >
                  ❤️
                </button>
              </div>

              {/* Swipe error toast */}
              {swipeError && (
                <div style={{ textAlign: 'center', marginTop: '12px' }}>
                  <span style={{ background: 'rgba(229,62,62,0.9)', color: 'white', fontSize: '13px', padding: '6px 16px', borderRadius: '20px' }}>
                    ⚠️ {swipeError}
                  </span>
                </div>
              )}

              {/* Undo button — one-level, appears after first swipe */}
              <div style={{ textAlign: 'center', marginTop: '16px', minHeight: '32px' }}>
                {canUndo && (
                  <button
                    disabled={swipeLoading}
                    onClick={handleUndo}
                    style={{ padding: '6px 18px', background: 'rgba(255,255,255,0.18)', color: 'white', border: '1px solid rgba(255,255,255,0.35)', borderRadius: '20px', fontSize: '13px', fontWeight: '500', cursor: swipeLoading ? 'not-allowed' : 'pointer', transition: 'background 0.15s', opacity: swipeLoading ? 0.5 : 1 }}
                    onMouseEnter={(e) => !swipeLoading && (e.currentTarget.style.background = 'rgba(255,255,255,0.28)')}
                    onMouseLeave={(e) => !swipeLoading && (e.currentTarget.style.background = 'rgba(255,255,255,0.18)')}
                  >
                    ↩️ Undo
                  </button>
                )}
                {undoMessage && (
                  <p style={{ color: 'rgba(255,255,255,0.9)', fontSize: '13px', margin: 0 }}>{undoMessage}</p>
                )}
              </div>
            </>
          )}
        </div>

        {/* Match popup */}
        {matchPopup && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
            <div style={{ background: 'white', borderRadius: '24px', padding: '48px 40px', maxWidth: '360px', width: '100%', textAlign: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.4)' }}>
              <div style={{ fontSize: '48px', marginBottom: '8px' }}>🎉</div>
              <h2 style={{ fontSize: '28px', fontWeight: '800', color: '#2d3748', marginBottom: '8px' }}>It's a Match!</h2>
              <p style={{ color: '#718096', fontSize: '15px', marginBottom: '24px' }}>
                You and {matchPopup.other_user?.name || 'someone'} liked each other!
              </p>
              <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', marginBottom: '28px', fontSize: '52px' }}>
                <span>{animalEmoji(avatarStatus?.animal)}</span>
                <span style={{ fontSize: '24px', alignSelf: 'center', color: '#ed64a6' }}>❤️</span>
                <span>{animalEmoji(matchPopup.other_user?.animal)}</span>
              </div>
              <button
                onClick={() => setMatchPopup(null)}
                style={{ width: '100%', padding: '14px', background: 'linear-gradient(135deg, #f687b3 0%, #ed64a6 100%)', color: 'white', border: 'none', borderRadius: '10px', fontSize: '16px', fontWeight: '700', cursor: 'pointer' }}
              >
                Keep Swiping
              </button>
              <button
                onClick={() => { setMatchPopup(null); setView('matches'); fetchMatches(); }}
                style={{ width: '100%', marginTop: '10px', padding: '12px', background: 'transparent', color: '#667eea', border: '2px solid #667eea', borderRadius: '10px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
              >
                View Matches
              </button>
            </div>
          </div>
        )}

        <style>{`
          @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
          .spinner { display: inline-block; animation: spin 2s linear infinite; }
        `}</style>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Matches view
  // ---------------------------------------------------------------------------
  if (view === 'matches') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 20px' }}>
        <div style={{ maxWidth: '800px', margin: '0 auto' }}>
          <Nav />

          <h2 style={{ color: 'white', fontSize: '22px', fontWeight: '600', marginBottom: '8px' }}>Your Matches</h2>
          <p style={{ color: 'rgba(255,255,255,0.75)', fontSize: '14px', marginBottom: '28px' }}>Spirit animals that connected with yours</p>

          {matchesError && (
            <div style={{ background: 'rgba(255,255,255,0.12)', border: '1px solid rgba(255,255,255,0.25)', borderRadius: '12px', padding: '20px 24px', marginBottom: '20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
              <p style={{ color: 'white', fontSize: '14px', margin: 0 }}>⚠️ {matchesError}</p>
              <button
                onClick={fetchMatches}
                style={{ padding: '6px 16px', background: 'white', color: '#667eea', border: 'none', borderRadius: '8px', fontSize: '13px', fontWeight: '600', cursor: 'pointer', flexShrink: 0 }}
              >
                Retry
              </button>
            </div>
          )}

          {matchesLoading ? (
            <div style={{ textAlign: 'center', color: 'white', padding: '60px', fontSize: '18px' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }} className="spinner">🐾</div>
              Loading matches…
            </div>
          ) : matches.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.8)', padding: '60px', background: 'rgba(255,255,255,0.1)', borderRadius: '16px' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>❤️</div>
              <p style={{ fontSize: '18px', fontWeight: '600' }}>No matches yet</p>
              <p style={{ fontSize: '14px', marginTop: '8px' }}>Go discover some spirit animals!</p>
              <button
                onClick={() => { setView('discover'); fetchDiscoverUsers(); }}
                style={{ marginTop: '20px', padding: '12px 28px', background: 'white', color: '#667eea', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '15px' }}
              >
                Discover People
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '16px' }}>
              {matches.map((m) => (
                <div
                  key={m.id}
                  onClick={() => openChat(m)}
                  style={{ background: 'white', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 4px 20px rgba(0,0,0,0.15)', transition: 'transform 0.2s', cursor: 'pointer' }}
                  onMouseEnter={(e) => e.currentTarget.style.transform = 'translateY(-4px)'}
                  onMouseLeave={(e) => e.currentTarget.style.transform = 'translateY(0)'}
                >
                  {/* Pink header: avatar + name + unread badge */}
                  <div style={{ background: 'linear-gradient(135deg, #f687b3 0%, #ed64a6 100%)', padding: '24px', textAlign: 'center', position: 'relative' }}>
                    {m.unread_count > 0 && (
                      <div style={{ position: 'absolute', top: '12px', right: '12px', background: '#e53e3e', color: 'white', borderRadius: '10px', fontSize: '11px', fontWeight: '700', padding: '2px 7px', minWidth: '18px', textAlign: 'center' }}>
                        {m.unread_count}
                      </div>
                    )}
                    <div style={{ fontSize: '56px', lineHeight: 1, marginBottom: '10px' }}>
                      {m.other_user.avatar_url ? (
                        <img src={avatarUrl(m.other_user.avatar_url)} alt="" style={{ width: '72px', height: '72px', borderRadius: '50%', objectFit: 'cover', border: '3px solid rgba(255,255,255,0.4)' }} onError={(e) => { e.target.style.display='none'; e.target.nextSibling.style.display='block'; }} />
                      ) : null}
                      <span style={{ display: m.other_user.avatar_url ? 'none' : 'block' }}>{animalEmoji(m.other_user.animal)}</span>
                    </div>
                    <h3 style={{ color: 'white', fontSize: '17px', fontWeight: '700', margin: 0 }}>
                      {m.other_user.name || 'Anonymous'}
                    </h3>
                    <p style={{ color: 'rgba(255,255,255,0.85)', fontSize: '13px', margin: '4px 0 0' }}>
                      {m.other_user.animal ? m.other_user.animal.charAt(0).toUpperCase() + m.other_user.animal.slice(1) : ''}
                    </p>
                  </div>
                  {/* Footer: last message preview or match date */}
                  <div style={{ padding: '12px 16px' }}>
                    {m.last_message ? (
                      <p style={{ color: '#4a5568', fontSize: '12px', margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        <span style={{ color: '#a0aec0' }}>
                          {m.last_message.sender_id === user?.id ? 'You: ' : ''}
                        </span>
                        {m.last_message.content}
                      </p>
                    ) : (
                      <p style={{ color: '#a0aec0', fontSize: '11px', margin: 0, textAlign: 'center' }}>
                        Matched {new Date(m.matched_at).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <style>{`
          @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
          .spinner { display: inline-block; animation: spin 2s linear infinite; }
        `}</style>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Chat view
  // ---------------------------------------------------------------------------
  if (view === 'chat' && currentMatch) {
    const other = currentMatch.other_user;

    const formatTime = (iso) =>
      new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const formatDate = (iso) => {
      const d = new Date(iso);
      const today = new Date();
      const yesterday = new Date(today - 86400000);
      if (d.toDateString() === today.toDateString()) return 'Today';
      if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    };

    // Group messages by date label
    const grouped = messages.reduce((acc, msg) => {
      const label = formatDate(msg.created_at);
      (acc[label] = acc[label] || []).push(msg);
      return acc;
    }, {});

    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', flexDirection: 'column' }}>

        {/* Chat header */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '14px', flexShrink: 0 }}>
          <button
            onClick={() => { setView('matches'); fetchMatches(); }}
            style={{ background: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.3)', color: 'white', borderRadius: '8px', padding: '8px 14px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
          >
            ← Matches
          </button>
          {other.avatar_url ? (
            <img
              src={avatarUrl(other.avatar_url)}
              alt={other.animal || 'avatar'}
              onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
              style={{ width: '44px', height: '44px', borderRadius: '50%', objectFit: 'cover', border: '2px solid rgba(255,255,255,0.4)', flexShrink: 0 }}
            />
          ) : null}
          <div style={{ fontSize: '36px', lineHeight: 1, display: other.avatar_url ? 'none' : 'block' }}>{animalEmoji(other.animal)}</div>
          <div>
            <p style={{ color: 'white', fontWeight: '700', fontSize: '17px', margin: 0 }}>{other.name || 'Anonymous'}</p>
            <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: '12px', margin: 0 }}>
              {other.animal ? other.animal.charAt(0).toUpperCase() + other.animal.slice(1) : ''}
            </p>
          </div>
        </div>

        {/* Message list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 16px', display: 'flex', flexDirection: 'column' }}>
          {messagesError ? (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.85)', marginTop: '60px', padding: '0 20px' }}>
              <div style={{ fontSize: '36px', marginBottom: '12px' }}>⚠️</div>
              <p style={{ fontSize: '15px', marginBottom: '16px' }}>{messagesError}</p>
              <button
                onClick={() => loadMessages(currentMatch.id)}
                style={{ padding: '10px 24px', background: 'white', color: '#667eea', border: 'none', borderRadius: '10px', fontWeight: '600', cursor: 'pointer', fontSize: '14px' }}
              >
                Try again
              </button>
            </div>
          ) : messagesLoading && messages.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.6)', marginTop: '40px' }}>
              <div style={{ fontSize: '32px', marginBottom: '8px' }} className="spinner">🐾</div>
              Loading…
            </div>
          ) : messages.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.75)', marginTop: '60px' }}>
              <div style={{ fontSize: '48px', marginBottom: '12px' }}>👋</div>
              <p style={{ fontSize: '17px', fontWeight: '600' }}>Start the conversation!</p>
              <p style={{ fontSize: '14px', marginTop: '6px', opacity: 0.8 }}>
                Say hi to {other.name || 'them'}!
              </p>
            </div>
          ) : (
            Object.entries(grouped).map(([dateLabel, msgs]) => (
              <div key={dateLabel}>
                {/* Date divider */}
                <div style={{ textAlign: 'center', margin: '16px 0 10px' }}>
                  <span style={{ background: 'rgba(0,0,0,0.25)', color: 'rgba(255,255,255,0.8)', fontSize: '11px', padding: '3px 12px', borderRadius: '10px' }}>
                    {dateLabel}
                  </span>
                </div>
                {msgs.map((msg) => (
                  <div key={msg.id} style={{ display: 'flex', justifyContent: msg.is_mine ? 'flex-end' : 'flex-start', marginBottom: '8px' }}>
                    <div style={{
                      maxWidth: '70%',
                      padding: '10px 14px',
                      borderRadius: msg.is_mine ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                      background: msg.is_mine ? 'white' : 'rgba(255,255,255,0.15)',
                      color: msg.is_mine ? '#2d3748' : 'white',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
                    }}>
                      <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.45', wordBreak: 'break-word' }}>{msg.content}</p>
                      <p style={{ margin: '4px 0 0', fontSize: '10px', opacity: 0.6, textAlign: 'right' }}>
                        {formatTime(msg.created_at)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Send error */}
        {sendError && (
          <div style={{ background: '#fff5f5', borderTop: '1px solid #fed7d7', padding: '8px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
            <p style={{ color: '#c53030', fontSize: '13px', margin: 0 }}>⚠️ {sendError}</p>
            <button onClick={sendMessage} style={{ padding: '4px 12px', background: '#c53030', color: 'white', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}>
              Retry
            </button>
          </div>
        )}

        {/* Message input */}
        <div style={{ background: 'white', padding: '12px 16px', display: 'flex', gap: '10px', alignItems: 'center', flexShrink: 0, borderTop: sendError ? 'none' : '1px solid #e2e8f0' }}>
          <input
            type="text"
            value={messageInput}
            onChange={(e) => setMessageInput(e.target.value.slice(0, 2000))}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            placeholder={`Message ${other.name || 'them'}…`}
            disabled={sending}
            style={{ flex: 1, padding: '11px 16px', border: '2px solid #e2e8f0', borderRadius: '24px', fontSize: '15px', outline: 'none', boxSizing: 'border-box' }}
            onFocus={(e) => e.target.style.borderColor = '#667eea'}
            onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
          />
          <button
            onClick={sendMessage}
            disabled={!messageInput.trim() || sending}
            style={{
              width: '44px', height: '44px', borderRadius: '50%', border: 'none', flexShrink: 0,
              background: (!messageInput.trim() || sending) ? '#e2e8f0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              cursor: (!messageInput.trim() || sending) ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px',
              transition: 'background 0.15s',
            }}
          >
            ➤
          </button>
        </div>

        <style>{`
          @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
          .spinner { display: inline-block; animation: spin 2s linear infinite; }
        `}</style>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Profile view (default)
  // ---------------------------------------------------------------------------
  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 20px' }}>
      <div style={{ maxWidth: '600px', margin: '0 auto' }}>
        <Nav />

        {/* Avatar Status Card */}
        <div style={{ background: 'white', borderRadius: '16px', padding: '32px', marginBottom: '24px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', textAlign: 'center' }}>
          {avatarStatus?.avatar_status === 'ready' && avatarStatus?.avatar_url ? (
            <img
              src={avatarUrl(avatarStatus.avatar_url)}
              alt={avatarStatus.animal || 'avatar'}
              onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
              style={{ width: '120px', height: '120px', borderRadius: '50%', objectFit: 'cover', marginBottom: '16px', border: '4px solid #e2e8f0', boxShadow: '0 4px 16px rgba(0,0,0,0.15)' }}
            />
          ) : null}
          <div style={{ fontSize: '64px', marginBottom: '16px', display: (avatarStatus?.avatar_status === 'ready' && avatarStatus?.avatar_url) ? 'none' : 'block' }}>
            {avatarStatus?.avatar_status === 'ready'
              ? animalEmoji(avatarStatus.animal)
              : getStatusEmoji()}
          </div>
          <h2 style={{ fontSize: '24px', fontWeight: '600', color: '#2d3748', marginBottom: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
            {getStatusText()}
            {avatarStatus?.avatar_status === 'ready' && avatarStatus?.animal && (
              <button onClick={handleCopyAnimal} style={{ padding: '4px 10px', background: copied ? '#48bb78' : '#edf2f7', color: copied ? 'white' : '#4a5568', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '500', cursor: 'pointer' }}>
                {copied ? 'Copied!' : '📋 Copy'}
              </button>
            )}
          </h2>
          {avatarStatus?.avatar_status === 'ready' && (
            <>
              {generationTime && (
                <p style={{ color: '#a0aec0', fontSize: '12px', marginBottom: '12px' }}>Generated in {generationTime}</p>
              )}
              {avatarStatus?.personality_traits?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center', marginBottom: '16px' }}>
                  {avatarStatus.personality_traits.map((trait, i) => (
                    <span key={i} style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', padding: '4px 12px', borderRadius: '16px', fontSize: '12px', fontWeight: '500' }}>
                      {trait}
                    </span>
                  ))}
                </div>
              )}
              {avatarStatus?.avatar_description && (
                <details style={{ textAlign: 'left', marginBottom: '12px' }}>
                  <summary style={{ cursor: 'pointer', color: '#667eea', fontSize: '13px', fontWeight: '500', userSelect: 'none' }}>View full description</summary>
                  <p style={{ marginTop: '8px', color: '#4a5568', fontSize: '14px', lineHeight: '1.6', padding: '12px', background: '#f7fafc', borderRadius: '8px' }}>
                    {avatarStatus.avatar_description}
                  </p>
                </details>
              )}
              <p style={{ color: '#718096', fontSize: '14px' }}>Update your bio to regenerate</p>
            </>
          )}
          {isGenerating && (
            <div style={{ marginTop: '16px', overflow: 'hidden' }}>
              <div style={{ width: '100%', height: '4px', background: '#e2e8f0', borderRadius: '2px', overflow: 'hidden' }}>
                <div style={{ width: '60%', height: '100%', background: 'linear-gradient(90deg, #667eea, #764ba2)', animation: 'slide 1.5s ease-in-out infinite' }}></div>
              </div>
            </div>
          )}
        </div>

        {/* Profile form */}
        <div style={{ background: 'white', borderRadius: '16px', padding: '32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
            <h3 style={{ fontSize: '20px', fontWeight: '600', color: '#2d3748' }}>Your Profile</h3>
            <span style={{ fontSize: '12px', color: '#718096', background: '#f7fafc', padding: '4px 12px', borderRadius: '12px' }}>{user?.email}</span>
          </div>

          {error && (
            <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030', fontSize: '14px' }}>{error}</div>
          )}

          <form onSubmit={isStale ? (e) => { e.preventDefault(); handleRegenerate(); } : handleUpdateBio}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr', gap: '16px', marginBottom: '20px' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Name</label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your first name" maxLength={100} style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Age</label>
                <input type="number" value={age} onChange={(e) => setAge(e.target.value)} placeholder="25" min={18} max={120} style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Location</label>
                <input type="text" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="City, State" maxLength={100} style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Tell us about yourself</label>
              <textarea value={bio} onChange={(e) => setBio(e.target.value)} placeholder="I'm a lone wolf who loves midnight runs and howling at the moon..." rows={4} style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box' }} onFocus={(e) => e.target.style.borderColor = '#667eea'} onBlur={(e) => e.target.style.borderColor = '#e2e8f0'} />
              <p style={{ fontSize: '12px', color: '#a0aec0', marginTop: '8px' }}>Claude will analyze your bio to determine your spirit animal</p>
            </div>

            <button
              type="submit"
              disabled={loading || (!isStale && (!bio.trim() || isGenerating))}
              style={{
                width: '100%', padding: '14px',
                background: loading || (!isStale && (!bio.trim() || isGenerating)) ? '#cbd5e0' : isStale ? 'linear-gradient(135deg, #f6ad55 0%, #ed8936 100%)' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600',
                cursor: loading || (!isStale && (!bio.trim() || isGenerating)) ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? (isStale ? 'Retrying...' : 'Updating...') : isStale ? '⚠️ Try Again' : isGenerating ? 'Generating...' : bio !== user?.bio ? 'Update Bio & Generate Avatar' : 'Regenerate Avatar'}
            </button>
          </form>
        </div>

        {/* Danger zone */}
        <div style={{ marginTop: '16px', background: 'white', borderRadius: '16px', padding: '24px 32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', border: '1px solid #fed7d7' }}>
          <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#c53030', marginBottom: '8px' }}>Danger Zone</h3>
          <p style={{ color: '#718096', fontSize: '13px', marginBottom: '16px' }}>
            Permanently delete your account and all data. This cannot be undone.
          </p>
          <button
            onClick={() => { setDeleteModalOpen(true); setDeleteConfirmText(''); setDeleteError(''); }}
            style={{ padding: '10px 20px', background: 'white', color: '#c53030', border: '2px solid #fc8181', borderRadius: '8px', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}
          >
            Delete Account
          </button>
        </div>

        <div style={{ marginTop: '24px', textAlign: 'center' }}>
          <a href="https://github.com/magicdevereaux/howl" target="_blank" rel="noopener noreferrer" style={{ color: 'rgba(255,255,255,0.8)', fontSize: '14px', textDecoration: 'none' }}>
            View on GitHub →
          </a>
        </div>
      </div>

      {/* Delete account confirmation modal */}
      {deleteModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ background: 'white', borderRadius: '16px', padding: '36px 32px', maxWidth: '400px', width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.35)' }}>
            <div style={{ fontSize: '40px', textAlign: 'center', marginBottom: '12px' }}>⚠️</div>
            <h2 style={{ fontSize: '20px', fontWeight: '800', color: '#2d3748', textAlign: 'center', marginBottom: '8px' }}>Delete your account?</h2>
            <p style={{ color: '#718096', fontSize: '14px', textAlign: 'center', marginBottom: '24px', lineHeight: '1.5' }}>
              This will permanently erase your profile, matches, and all messages. There is no undo.
            </p>

            <label style={{ display: 'block', color: '#4a5568', fontSize: '13px', fontWeight: '600', marginBottom: '6px' }}>
              Type <span style={{ fontFamily: 'monospace', background: '#f7fafc', padding: '1px 6px', borderRadius: '4px' }}>DELETE</span> to confirm
            </label>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="DELETE"
              style={{ width: '100%', padding: '10px 12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '15px', marginBottom: '16px', boxSizing: 'border-box', fontFamily: 'monospace' }}
              onFocus={(e) => e.target.style.borderColor = '#fc8181'}
              onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
            />

            {deleteError && (
              <p style={{ color: '#c53030', fontSize: '13px', marginBottom: '12px', textAlign: 'center' }}>⚠️ {deleteError}</p>
            )}

            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                onClick={() => { setDeleteModalOpen(false); setDeleteConfirmText(''); setDeleteError(''); }}
                disabled={deleteLoading}
                style={{ flex: 1, padding: '12px', background: '#f7fafc', color: '#4a5568', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '15px', fontWeight: '600', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleteConfirmText !== 'DELETE' || deleteLoading}
                style={{
                  flex: 1, padding: '12px',
                  background: (deleteConfirmText === 'DELETE' && !deleteLoading) ? '#c53030' : '#fc8181',
                  color: 'white', border: 'none', borderRadius: '8px', fontSize: '15px', fontWeight: '700',
                  cursor: (deleteConfirmText === 'DELETE' && !deleteLoading) ? 'pointer' : 'not-allowed',
                }}
              >
                {deleteLoading ? 'Deleting…' : 'Delete forever'}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(250%); } }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spinner { display: inline-block; animation: spin 2s linear infinite; }
      `}</style>
    </div>
  );
}
