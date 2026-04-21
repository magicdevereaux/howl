import React, { useState, useEffect } from 'react';

export default function HowlApp() {
  const [view, setView] = useState('login'); // 'login', 'register', 'profile'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [bio, setBio] = useState('');
  const [token, setToken] = useState(localStorage.getItem('access_token') || '');
  const [user, setUser] = useState(null);
  const [avatarStatus, setAvatarStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [generationStartTime, setGenerationStartTime] = useState(null);
  const [generationTime, setGenerationTime] = useState(null);

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

  // Fetch profile on mount if token exists
  useEffect(() => {
    if (token) {
      fetchProfile();
      fetchAvatarStatus();
    }
  }, [token]);

  // Poll only when generation is actively in progress (bio exists + pending/generating + not stale)
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

  const fetchProfile = async () => {
    try {
      const res = await fetch(`${API_URL}/api/profile/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
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

  // currentToken is an explicit override for cases where the React state
  // hasn't updated yet (stale closure after login/register).
  const fetchAvatarStatus = async (currentToken) => {
    const authToken = currentToken !== undefined ? currentToken : token;
    try {
      const res = await fetch(`${API_URL}/api/avatar/status`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        setAvatarStatus(prev => {
          // If we just transitioned to ready, record elapsed time
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
        // Token is invalid or expired — clear session and return to login
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
        setBio(data.user.bio || '');
        setView('profile');
        fetchAvatarStatus(newToken); // pass token explicitly — avoids stale closure
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
        // FIX: register now returns {access_token, user} matching login shape
        setToken(data.access_token);
        localStorage.setItem('access_token', data.access_token);
        setUser(data.user);
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
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ bio })
      });

      const data = await res.json();

      if (res.ok) {
        setUser(data);
        setGenerationStartTime(Date.now());
        setGenerationTime(null);
        // Local sentinel so the UI reacts immediately before the first poll
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
    setBio('');
    setView('login');
    localStorage.removeItem('access_token');
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

  if (view === 'register') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <h1 style={{ fontSize: '32px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Join Howl 🐺</h1>
          <p style={{ color: '#718096', marginBottom: '32px', textAlign: 'center' }}>Create your account</p>

          {error && (
            <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleRegister}>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="wolf@howl.app"
                required
                style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', transition: 'border 0.2s', boxSizing: 'border-box' }}
                onFocus={(e) => e.target.style.borderColor = '#667eea'}
                onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
              />
            </div>

            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', transition: 'border 0.2s', boxSizing: 'border-box' }}
                onFocus={(e) => e.target.style.borderColor = '#667eea'}
                onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{ width: '100%', padding: '14px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', transition: 'transform 0.2s' }}
              onMouseEnter={(e) => !loading && (e.target.style.transform = 'translateY(-2px)')}
              onMouseLeave={(e) => !loading && (e.target.style.transform = 'translateY(0)')}
            >
              {loading ? 'Creating account...' : 'Create Account'}
            </button>
          </form>

          <p style={{ marginTop: '24px', textAlign: 'center', color: '#718096', fontSize: '14px' }}>
            Already have an account?{' '}
            <button onClick={() => setView('login')} style={{ color: '#667eea', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>
              Sign in
            </button>
          </p>
        </div>
      </div>
    );
  }

  if (view === 'login') {
    return (
      <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
        <div style={{ background: 'white', borderRadius: '16px', padding: '40px', maxWidth: '400px', width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.3)' }}>
          <h1 style={{ fontSize: '32px', fontWeight: '700', color: '#2d3748', marginBottom: '8px', textAlign: 'center' }}>Welcome to Howl 🐺</h1>
          <p style={{ color: '#718096', marginBottom: '32px', textAlign: 'center' }}>Sign in to find your spirit animal</p>

          {error && (
            <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="wolf@howl.app"
                required
                style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', transition: 'border 0.2s', boxSizing: 'border-box' }}
                onFocus={(e) => e.target.style.borderColor = '#667eea'}
                onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
              />
            </div>

            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', transition: 'border 0.2s', boxSizing: 'border-box' }}
                onFocus={(e) => e.target.style.borderColor = '#667eea'}
                onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{ width: '100%', padding: '14px', background: loading ? '#a0aec0' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: '600', cursor: loading ? 'not-allowed' : 'pointer', transition: 'transform 0.2s' }}
              onMouseEnter={(e) => !loading && (e.target.style.transform = 'translateY(-2px)')}
              onMouseLeave={(e) => !loading && (e.target.style.transform = 'translateY(0)')}
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          <p style={{ marginTop: '24px', textAlign: 'center', color: '#718096', fontSize: '14px' }}>
            Don't have an account?{' '}
            <button onClick={() => setView('register')} style={{ color: '#667eea', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: '14px', fontWeight: '600' }}>
              Create one
            </button>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', padding: '40px 20px' }}>
      <div style={{ maxWidth: '600px', margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
          <h1 style={{ fontSize: '32px', fontWeight: '700', color: 'white' }}>Howl 🐺</h1>
          <button
            onClick={handleLogout}
            style={{ padding: '10px 20px', background: 'rgba(255,255,255,0.2)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: '500' }}
          >
            Logout
          </button>
        </div>

        {/* Avatar Status Card */}
        <div style={{ background: 'white', borderRadius: '16px', padding: '32px', marginBottom: '24px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)', textAlign: 'center' }}>
          <div style={{ fontSize: '64px', marginBottom: '16px' }}>{getStatusEmoji()}</div>
          <h2 style={{ fontSize: '24px', fontWeight: '600', color: '#2d3748', marginBottom: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
            {getStatusText()}
            {avatarStatus?.avatar_status === 'ready' && avatarStatus?.animal && (
              <button
                onClick={handleCopyAnimal}
                style={{ padding: '4px 10px', background: copied ? '#48bb78' : '#edf2f7', color: copied ? 'white' : '#4a5568', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: '500', cursor: 'pointer', transition: 'all 0.2s' }}
              >
                {copied ? 'Copied!' : '📋 Copy'}
              </button>
            )}
          </h2>
          {avatarStatus?.avatar_status === 'ready' && (
            <>
              {generationTime && (
                <p style={{ color: '#a0aec0', fontSize: '12px', marginBottom: '12px' }}>
                  Generated in {generationTime}
                </p>
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
                  <summary style={{ cursor: 'pointer', color: '#667eea', fontSize: '13px', fontWeight: '500', userSelect: 'none' }}>
                    View full description
                  </summary>
                  <p style={{ marginTop: '8px', color: '#4a5568', fontSize: '14px', lineHeight: '1.6', padding: '12px', background: '#f7fafc', borderRadius: '8px' }}>
                    {avatarStatus.avatar_description}
                  </p>
                </details>
              )}
              <p style={{ color: '#718096', fontSize: '14px' }}>
                Update your bio to regenerate
              </p>
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

        {/* Profile Card */}
        <div style={{ background: 'white', borderRadius: '16px', padding: '32px', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }}>
          <div style={{ marginBottom: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '20px', fontWeight: '600', color: '#2d3748' }}>Your Profile</h3>
              <span style={{ fontSize: '12px', color: '#718096', background: '#f7fafc', padding: '4px 12px', borderRadius: '12px' }}>
                {user?.email}
              </span>
            </div>
          </div>

          {error && (
            <div style={{ background: '#fee', border: '1px solid #fcc', borderRadius: '8px', padding: '12px', marginBottom: '20px', color: '#c53030', fontSize: '14px' }}>
              {error}
            </div>
          )}

          <form onSubmit={isStale ? (e) => { e.preventDefault(); handleRegenerate(); } : handleUpdateBio}>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', color: '#4a5568', fontWeight: '500', fontSize: '14px' }}>
                Tell us about yourself
              </label>
              <textarea
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                placeholder="I'm a lone wolf who loves midnight runs and howling at the moon..."
                rows={4}
                style={{ width: '100%', padding: '12px', border: '2px solid #e2e8f0', borderRadius: '8px', fontSize: '16px', fontFamily: 'inherit', resize: 'vertical', transition: 'border 0.2s', boxSizing: 'border-box' }}
                onFocus={(e) => e.target.style.borderColor = '#667eea'}
                onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
              />
              <p style={{ fontSize: '12px', color: '#a0aec0', marginTop: '8px' }}>
                Claude will analyze your bio to determine your spirit animal
              </p>
            </div>

            <button
              type="submit"
              disabled={loading || (!isStale && (!bio.trim() || isGenerating))}
              style={{
                width: '100%',
                padding: '14px',
                background: loading || (!isStale && (!bio.trim() || isGenerating)) ? '#cbd5e0' : isStale ? 'linear-gradient(135deg, #f6ad55 0%, #ed8936 100%)' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                fontSize: '16px',
                fontWeight: '600',
                cursor: loading || (!isStale && (!bio.trim() || isGenerating)) ? 'not-allowed' : 'pointer',
                transition: 'transform 0.2s'
              }}
              onMouseEnter={(e) => {
                if (!loading && (isStale || (bio.trim() && !isGenerating))) {
                  e.target.style.transform = 'translateY(-2px)';
                }
              }}
              onMouseLeave={(e) => {
                if (!loading && (isStale || (bio.trim() && !isGenerating))) {
                  e.target.style.transform = 'translateY(0)';
                }
              }}
            >
              {loading ? (isStale ? 'Retrying...' : 'Updating...') : isStale ? '⚠️ Try Again' : isGenerating ? 'Generating...' : bio !== user?.bio ? 'Update Bio & Generate Avatar' : 'Regenerate Avatar'}
            </button>
          </form>
        </div>

        {/* FIX: restored missing opening <a> tag */}
        <div style={{ marginTop: '24px', textAlign: 'center' }}>
          <a
            href="https://github.com/magicdevereaux/howl"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'rgba(255,255,255,0.8)', fontSize: '14px', textDecoration: 'none' }}
          >
            View on GitHub →
          </a>
        </div>
      </div>

      <style>{`
        @keyframes slide {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(250%); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .spinner {
          display: inline-block;
          animation: spin 2s linear infinite;
        }
      `}</style>
    </div>
  );
}
