import React, { useCallback, useState, useEffect, useRef } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { WS_URL } from './utils';
import {
  apiFetch,
  isVerificationBlocked,
  isVerificationErrorFrame,
  reportVerificationRequired,
  WS_TERMINAL_CLOSE_CODES,
} from './api/client';
import { WS_RECONNECT_DELAY_MS } from './shared/constants';
import EmailVerificationBanner from './components/EmailVerificationBanner';
import { EmailVerificationProvider } from './contexts/EmailVerificationContext';
import ReportModal from './components/ReportModal';
import DiscoverView from './components/DiscoverView';
import LegalPage from './components/LegalPage';
import LoginView from './components/LoginView';
import MatchesView from './components/MatchesView';
import PasswordReset from './components/PasswordReset';
import ProfileView from './components/ProfileView';
import RegisterView from './components/RegisterView';
import Splash from './components/Splash';
import ChatRoute from './routes/ChatRoute';
import RequireAuth from './routes/RequireAuth';
import { PATHS, chatPath, pathForView, viewForPath } from './routes/paths';

// Display-only starting value for the "N swipes left" counter.
//
// It is NOT the rule. `_DAILY_SWIPE_LIMIT` in app/api/swipes.py is the only
// authority, and the server never lets a swipe through past it regardless of
// what this says. `UserOut` does not carry the quota today, so the client has
// nothing to read until the server rejects a swipe with
// `429 {code: 'daily_limit_reached', limit: N}` — at which point the real
// value replaces this one for the rest of the session.
//
// Follow-up that removes the guess entirely: add `daily_swipe_limit` to
// UserOut so /api/auth/me reports it up front. See docs/GAPS.md #32.
const FALLBACK_DAILY_SWIPE_LIMIT = 20;

/**
 * Password-reset and verify-email links point at the *site root* with a query
 * string — `app/services/email.py:24,44` builds `{frontend_url}?token=…` and
 * `{frontend_url}?verify=…`. So the tokens have to be captured before anything
 * rewrites the URL, and read once per mount rather than once per render: the
 * effect below strips the query so the token never reaches browser history,
 * after which a re-read would come back empty.
 */
function readUrlTokens() {
  const params = new URLSearchParams(window.location.search);
  return { reset: params.get('token') || '', verify: params.get('verify') || '' };
}

export default function HowlApp() {
  const [urlTokens] = useState(readUrlTokens);
  const navigate = useNavigate();
  // Not `location` — that name is already taken by the user's city, below.
  const routerLocation = useLocation();

  // The URL is now the authority for what renders. `view` is derived from it,
  // and `setView` is a shim onto navigate() so the extracted view components
  // can keep calling setView('matches') while they are converted.
  const view = viewForPath(routerLocation.pathname);
  const setView = useCallback((next) => navigate(pathForView(next)), [navigate]);

  // True until the cookie session check settles. Without it a deep link to a
  // protected route would bounce to /login before we knew whether there was a
  // session — the old client had the milder version of the same bug, showing a
  // flash of the login form to every returning user.
  const [booting, setBooting] = useState(true);
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
  // Auth is now handled via httpOnly cookies — no token in JS state.
  const [user, setUser] = useState(null);
  const [avatarStatus, setAvatarStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [discoverUsers, setDiscoverUsers] = useState([]);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState('');
  const [matches, setMatches] = useState([]);
  // Whether the match list has completed a fetch at least once. `/chat/:matchId`
  // needs to tell "not fetched yet" from "fetched, and that match isn't yours".
  const [matchesLoaded, setMatchesLoaded] = useState(false);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [matchesError, setMatchesError] = useState('');
  const [matchPopup, setMatchPopup] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [blocksLoading, setBlocksLoading] = useState(false);
  const [swipeLoading, setSwipeLoading] = useState(false);
  const [swipeError, setSwipeError] = useState('');
  const [canUndo, setCanUndo] = useState(false);
  const [undoMessage, setUndoMessage] = useState('');
  // The daily swipe quota is enforced by the backend (app/api/swipes.py) and it
  // is the only authority on the number. The server does not advertise it until
  // it rejects a swipe, so this starts as an optimistic display value and is
  // replaced by `detail.limit` from the 429 the moment the server disagrees.
  // Never treat it as the rule — it only decides what the counter renders.
  const [swipeLimit, setSwipeLimit] = useState(FALLBACK_DAILY_SWIPE_LIMIT);
  const [currentMatch, setCurrentMatch] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState('');
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [messageInput, setMessageInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const [typingUser, setTypingUser] = useState(null); // display name of who's typing

  const chatWsRef = useRef(null);       // holds the live WebSocket for sending
  const typingTimerRef = useRef(null);  // auto-clears the typing indicator
  // Whether this conversation's socket has opened before. Distinguishes the
  // first connect (history was just loaded) from a reconnect (it may be stale).
  const hasConnectedRef = useRef(false);
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
  const [resetToken, setResetToken] = useState(urlTokens.reset);
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

  // The chat socket keys off this primitive, not off `currentMatch`. See the
  // WebSocket effect below for why that distinction is load-bearing.
  const currentMatchId = currentMatch?.id ?? null;

  // ---------------------------------------------------------------------------
  // Fetchers with stable identities.
  //
  // Every one of these is called from an effect, so each must keep the same
  // identity across renders — a fetcher recreated each render either loops the
  // effect or has to be omitted from its dependency array and lie about it.
  //
  // Two rules hold this block together:
  //
  //  1. They are declared *here*, above every effect that lists them. A `const`
  //     is in the temporal dead zone until its declaration is reached, and a
  //     hook's dependency array is evaluated during render — so naming a
  //     callback declared further down throws "Cannot access '<minified>'
  //     before initialization" in the production bundle. That is the GAPS #12
  //     failure, and it is why the derived state above sits where it does.
  //  2. Their dep lists are honest, not empty-by-convenience. They close over
  //     state setters (stable by contract) and module constants only, so `[]`
  //     is the truth; `fetchProfile` names the two fetchers it calls.
  // ---------------------------------------------------------------------------
  const loadMessages = useCallback(async (matchId) => {
    setMessagesLoading(true);
    setMessagesError('');
    try {
      const res = await apiFetch(`/api/matches/${matchId}/messages`, {

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
  }, []);

  const fetchAvatarStatus = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/avatar/status`, {});
      if (res.ok) {
        setAvatarStatus(await res.json());
      } else if (res.status === 401) {
        // Clearing the user is what sends us to /login now — RequireAuth
        // reacts to it. Previously this only swapped the view, leaving a stale
        // user object behind that the profile screen would still render from.
        setUser(null);
      }
    } catch (err) {
      console.error('Failed to fetch avatar status', err);
    }
  }, []);

  const fetchDiscoverUsers = useCallback(async () => {
    setDiscoverLoading(true);
    setDiscoverError('');
    try {
      const res = await apiFetch(`/api/users/discover`, {

      });
      if (res.ok) {
        setDiscoverUsers(await res.json());
      } else if (res.status === 401) {
        setUser(null);
        setError('Session expired. Please sign in again.');
      } else {
        setDiscoverError('Failed to load users');
      }
    } catch {
      setDiscoverError('Network error');
    } finally {
      setDiscoverLoading(false);
    }
  }, []);

  const fetchMatches = useCallback(async () => {
    setMatchesLoading(true);
    setMatchesError('');
    try {
      const res = await apiFetch(`/api/users/matches`, {

      });
      if (res.ok) {
        setMatches(await res.json());
        setMatchesLoaded(true);
      } else if (res.status === 401) {
        setUser(null);
        setError('Session expired. Please sign in again.');
      } else {
        setMatchesError("Couldn't load your matches.");
      }
    } catch {
      setMatchesError('Network error — check your connection.');
    } finally {
      setMatchesLoading(false);
    }
  }, []);

  const fetchProfile = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/profile/me`, {
        credentials: 'include'
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
        fetchAvatarStatus();
        fetchMatches();
      }
      // 401 means no valid cookie — stay signed out silently
    } catch { /* network error — stay signed out */ }
    finally { setBooting(false); }
  }, [fetchAvatarStatus, fetchMatches]);

  // On mount, attempt to restore the session from the cookie. It does not
  // navigate: on a deep link to /discover, forcing /profile after the session
  // check would defeat the whole point of having URLs. The index route and
  // RequireAuth decide where an unrouted visit lands.
  //
  // `fetchProfile` is in the dependency list rather than suppressed: its
  // identity is stable, so naming it honestly still means "run once". There was
  // never a staleness bug here — the empty array was hiding a lie, not a fix.
  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  useEffect(() => {
    const shouldPoll =
      (avatarStatus?.avatar_status === 'pending' || avatarStatus?.avatar_status === 'generating') &&
      !!user?.bio &&
      !isStale;
    if (shouldPoll) {
      const interval = setInterval(fetchAvatarStatus, 3000);
      return () => clearInterval(interval);
    }
  }, [avatarStatus?.avatar_status, user?.bio, isStale, fetchAvatarStatus]);

  // WebSocket connection for real-time chat delivery.
  // Replaces the previous 3-second polling approach.
  // Reconnects automatically after WS_RECONNECT_DELAY_MS whenever the
  // connection drops (network glitch, server restart, etc.). The delay is
  // shared with the mobile client — see src/shared/constants.js.
  //
  // Keyed on the match *id*, never the match object. The linter asked for
  // `currentMatch` here and it was right that the array was incomplete, but
  // adding the object would have been the wrong fix: `matches` is refetched on
  // every entry to /matches and on every unread change, and each refetch mints
  // new objects. Depending on identity would tear down and rebuild this socket
  // each time — dropping live delivery mid-conversation and, now that reconnect
  // refetches history, firing a redundant request with it. The socket's
  // identity is the conversation, and a conversation is an id.
  useEffect(() => {
    if (view !== 'chat' || !currentMatchId) return;

    const wsUrl = `${WS_URL}/api/matches/${currentMatchId}/ws`;
    let ws = null;
    let reconnectTimer = null;
    let active = true; // false after cleanup so reconnect attempts stop
    hasConnectedRef.current = false; // per conversation, not per app session

    const connect = () => {
      if (!active) return;
      ws = new WebSocket(wsUrl);

      chatWsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const { type, message, user_name } = data;
          if (isVerificationErrorFrame(data)) {
            // Sent immediately before the server closes with 4403. Reporting it
            // here is what gives the notice the server's own wording; the close
            // handler below only needs to not retry.
            reportVerificationRequired(data.error);
          } else if (type === 'new_message') {
            setMessages((prev) => {
              const byId = new Map(prev.map((m) => [m.id, m]));
              byId.set(message.id, message);
              return Array.from(byId.values()).sort((a, b) => a.id - b.id);
            });
            // They sent a message — clear the typing indicator immediately
            setTypingUser(null);
            if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
          } else if (type === 'message_deleted') {
            setMessages((prev) => prev.map((m) => m.id === message.id ? message : m));
          } else if (type === 'typing') {
            setTypingUser(user_name || 'Someone');
            if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
            typingTimerRef.current = setTimeout(() => setTypingUser(null), 2500);
          }
        } catch { /* ignore malformed frames */ }
      };

      ws.onclose = (event) => {
        chatWsRef.current = null;
        if (!active) return;
        // Some refusals are permanent. 4403 (email not verified), 4001 (not
        // authenticated) and 4003 (not your match) are all decisions about this
        // identity and this match, so retrying returns the same answer — and
        // retrying every 2.5s for as long as the tab is open is a denial of
        // service aimed at ourselves. Reconnect only for transient closes.
        if (WS_TERMINAL_CLOSE_CODES.has(event?.code)) return;
        reconnectTimer = setTimeout(connect, WS_RECONNECT_DELAY_MS);
      };

      // Redis pub/sub is fire-and-forget: an event published while this replica
      // was disconnected is dropped with no replay (app/services/pubsub.py).
      // The message rows are committed to Postgres before broadcast, so the
      // history endpoint is the source of truth — but only if someone asks it.
      // Refetching on every *re*connect is that ask (GAPS-ROUND-2 #47).
      ws.onopen = () => {
        if (!active) return;
        if (hasConnectedRef.current) loadMessages(currentMatchId);
        hasConnectedRef.current = true;
      };

      ws.onerror = () => {
        ws.close(); // triggers onclose → schedules reconnect
      };
    };

    connect();

    return () => {
      active = false;
      chatWsRef.current = null;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      setTypingUser(null);
      if (ws) ws.close();
    };
  }, [view, currentMatchId, loadMessages]);

  // Remove ?token= / ?verify= from the URL so tokens aren't visible in browser
  // history. `urlTokens` is stable (useState initialiser), so this runs once.
  useEffect(() => {
    if (urlTokens.reset || urlTokens.verify) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, [urlTokens]);

  // Process an email verification link clicked from the user's inbox.
  useEffect(() => {
    if (!urlTokens.verify) return;
    (async () => {
      try {
        const res = await apiFetch(`/api/auth/verify-email`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: urlTokens.verify }),
        });
        if (res.ok) {
          setUser(prev => prev ? { ...prev, is_email_verified: true } : prev);
        }
      } catch { /* ignore — the banner stays until the next profile fetch */ }
    })();
  }, [urlTokens]);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await apiFetch(`/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (res.ok) {
        // Cookie is set by the server; just update local UI state
        setUser(data.user);
        setName(data.user.name || '');
        setLocation(data.user.location || '');
        setBio(data.user.bio || '');
        // Land where they were headed if a deep link bounced them here
        // (RequireAuth records it), otherwise the profile as before.
        navigate(routerLocation.state?.from || PATHS.profile, { replace: true });
        fetchAvatarStatus();
        fetchMatches();
      } else {
        setError(data.detail || 'Login failed');
      }
    } catch (err) {
      // Sign-in failing at the network layer is the most expensive failure in
      // the app to diagnose blind — it is indistinguishable from a wrong
      // password to the user and from nothing at all to us.
      console.error('Login request failed', err);
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
      const res = await apiFetch(`/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (res.ok) {
        setUser(data.user);
        setName(data.user.name || '');
        setLocation(data.user.location || '');
        setBio(data.user.bio || '');
        setView('profile');
      } else {
        setError(data.detail || 'Registration failed');
      }
    } catch (err) {
      console.error('Registration request failed', err);
      setError('Network error');
    } finally {
      setLoading(false);
    }
  };

  // handleSaveProfile — used by the Profile edit/save flow.
  // Takes draft values explicitly so ProfileView can own its own editing state.
  // Returns true on success so ProfileView can exit edit mode.
  const handleSaveProfile = async ({ name: n, age: a, location: l, bio: b }) => {
    setError('');
    setLoading(true);
    try {
      const res = await apiFetch(`/api/profile/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ name: n || null, age: a ? parseInt(a, 10) : null, location: l || null, bio: b || null }),
      });
      const data = await res.json();
      if (res.ok) {
        setUser(data);
        setName(data.name || '');
        setAge(data.age ? String(data.age) : '');
        setLocation(data.location || '');
        setBio(data.bio || '');
        // If the backend queued a regen, start the generation spinner
        if (data.avatar_status === 'pending') {
          setAvatarStatus({ avatar_status: 'generating', animal: null });
          setTimeout(fetchAvatarStatus, 2000);
        }
        return true;
      } else {
        setError(typeof data.detail === 'string' ? data.detail : 'Update failed');
        return false;
      }
    } catch {
      setError('Network error');
      return false;
    } finally {
      setLoading(false);
    }
  };

  // `handleUpdateBio` used to live here: a second, drifted copy of the profile
  // save that nothing rendered. ProfileView owns its own draft state and calls
  // handleSaveProfile above; the bio form this served was replaced during the
  // component extraction and the function was left behind, still referencing
  // the `generationStartTime` state that GAPS #12 deleted. Removed rather than
  // underscore-prefixed — there is nothing here to keep.

  const handleLogout = () => {
    // Server clears both cookies; fire-and-forget
    apiFetch(`/api/auth/logout`, { method: 'POST' }).catch(() => {});
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
    setMatchesLoaded(false);
    navigate(PATHS.login, { replace: true });
  };

  const handleDeleteAccount = async () => {
    setDeleteLoading(true);
    setDeleteError('');
    try {
      const res = await apiFetch(`/api/profile/me`, {
        method: 'DELETE',

      });
      if (res.status === 204) {
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
        setMatchesLoaded(false);
        setDeleteModalOpen(false);
        setDeleteConfirmText('');
        navigate(PATHS.register, { replace: true });
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
      await apiFetch(`/api/auth/forgot-password`, {
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
      const res = await apiFetch(`/api/auth/reset-password`, {
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

  const handleDeleteMessage = async (messageId) => {
    if (!currentMatch) return;
    try {
      const res = await apiFetch(
        `/api/matches/${currentMatch.id}/messages/${messageId}`,
        { method: 'DELETE', credentials: 'include' },
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
      const res = await apiFetch(
        `/api/matches/${currentMatch.id}/messages?before_id=${oldestId}`,
        {},
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
      const res = await apiFetch(`/api/matches/${currentMatch.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ content }),
      });
      if (res.ok) {
        const msg = await res.json();
        setMessages(prev => {
          const byId = new Map(prev.map((m) => [m.id, m]));
          byId.set(msg.id, msg);
          return Array.from(byId.values()).sort((a, b) => a.id - b.id);
        });
      } else {
        // Put the text back either way — losing what someone typed is worse
        // than any error message. But stay quiet about *why* when the global
        // verification notice is already saying it: "Message failed to send —
        // please try again" next to "verify your email" reads as two unrelated
        // faults, and "try again" is advice that cannot work.
        setMessageInput(content);
        if (!isVerificationBlocked(res)) {
          setSendError("Message failed to send — please try again.");
        }
      }
    } catch {
      setMessageInput(content);
      setSendError('Network error — message not sent.');
    } finally {
      setSending(false);
    }
  };

  const sendTypingEvent = () => {
    const ws = chatWsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'typing' }));
    }
  };

  /**
   * Bind the chat state to a match and load its history.
   *
   * Split from navigation on purpose: `/chat/:matchId` has to be openable cold
   * (pasted link, refresh, notification), so ChatRoute calls this from an
   * effect once it has resolved the id. `openChat` is the click path and does
   * both.
   */
  const bindChat = useCallback((match) => {
    setTypingUser(null);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    setCurrentMatch(match);
    setMessages([]);
    setMessagesError('');
    setSendError('');
    loadMessages(match.id);
  }, [loadMessages]);

  const openChat = (match) => {
    bindChat(match);
    navigate(chatPath(match.id));
  };

  const fetchBlocks = async () => {
    setBlocksLoading(true);
    try {
      const res = await apiFetch(`/api/blocks`, {

      });
      if (res.ok) setBlocks(await res.json());
    } catch { /* ignore */ }
    finally { setBlocksLoading(false); }
  };

  const handleUnmatch = async (matchId) => {
    await apiFetch(`/api/matches/${matchId}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    setCurrentMatch(null);
    setMessages([]);
    navigate(PATHS.matches, { replace: true });
    fetchMatches();
  };

  const handleBlockAndReport = async (userId, reason, notes) => {
    await handleBlock(userId); // navigate away and reload matches
    try {
      await apiFetch(`/api/reports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({
          reported_user_id: userId,
          reason,
          ...(notes ? { notes } : {}),
        }),
      });
    } catch { /* block succeeded — report failure is non-critical */ }
  };

  const handleBlock = async (userId) => {
    await apiFetch(`/api/blocks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify({ blocked_id: userId }),
    });
    // Remove from discover stack if present
    setDiscoverUsers(prev => prev.filter(u => u.id !== userId));
    // If blocking from chat, go back to matches
    if (currentMatch?.other_user?.id === userId) {
      setCurrentMatch(null);
      setMessages([]);
      navigate(PATHS.matches, { replace: true });
      fetchMatches();
    }
    fetchBlocks();
  };

  const handleUnblock = async (userId) => {
    await apiFetch(`/api/blocks/${userId}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    setBlocks(prev => prev.filter(b => b.id !== userId));
  };

  const handleRegenerate = async () => {
    setError('');
    setLoading(true);
    try {
      const res = await apiFetch(`/api/avatar/regenerate`, {
        method: 'POST',

      });
      const data = await res.json();
      if (res.ok) {
        setAvatarStatus(data);
      } else if (res.status === 429 && data.detail?.code === 'regeneration_limit_reached') {
        const resets = new Date(data.detail.resets_at);
        const resetStr = resets.toLocaleDateString([], { month: 'long', day: 'numeric' });
        setError(`You've used your free regeneration for this month. Resets on ${resetStr}.`);
      } else if (isVerificationBlocked(res)) {
        // The global notice covers it, with the server's wording.
      } else {
        setError(typeof data.detail === 'string' ? data.detail : 'Regeneration failed');
      }
    } catch (err) {
      // The user gets the same message either way, but a DNS failure, a CORS
      // rejection and a TypeError from a bad body all land here and are not the
      // same problem. Logging the cause is the difference between a bug report
      // that can be acted on and "it says network error".
      console.error('Avatar regeneration request failed', err);
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
      const res = await apiFetch(`/api/reports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },

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
      await apiFetch(`/api/profile/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },

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
      await apiFetch(`/api/profile/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ email_notifications: enabled }),
      });
    } catch { /* silently revert on network error */ }
  };

  const handleSwipe = async (targetUserId, direction) => {
    setSwipeLoading(true);
    setUndoMessage('');
    setSwipeError('');
    try {
      const res = await apiFetch(`/api/swipes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ target_user_id: targetUserId, direction }),
      });
      const data = await res.json();

      // Return *before* the stack advances. The swipe was refused, so the card
      // is still undecided — discarding it would silently cost the user a
      // profile they never got to answer, and there is no way back to it.
      if (isVerificationBlocked(res)) return;

      if (res.status === 429 && data.detail?.code === 'daily_limit_reached') {
        // The server just told us the real quota. Adopt it, then mark the
        // counter exhausted — no full profile refetch needed.
        const serverLimit = Number(data.detail.limit);
        const limit = Number.isFinite(serverLimit) && serverLimit > 0 ? serverLimit : swipeLimit;
        setSwipeLimit(limit);
        setUser(prev => prev ? { ...prev, daily_swipes: limit } : prev);
        return;
      }

      setDiscoverUsers(prev => prev.slice(1));
      setCanUndo(true);
      if (res.ok && data.matched) {
        setMatchPopup(data.match);
      } else if (!res.ok) {
        setSwipeError('Swipe failed — tap to try again.');
        setTimeout(() => setSwipeError(''), 4000);
      }
      if (res.ok) {
        setUser(prev => prev ? { ...prev, daily_swipes: (prev.daily_swipes || 0) + 1 } : prev);
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
      const res = await apiFetch(`/api/swipes/last`, {
        method: 'DELETE',

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
  const navProps = { view, setView, handleLogout, totalUnread };

  const swipeLimitReached = !user?.is_premium && (user?.daily_swipes || 0) >= swipeLimit;
  const swipesRemaining = user?.is_premium ? null : Math.max(0, swipeLimit - (user?.daily_swipes || 0));

  // ---------------------------------------------------------------------------
  // Data on route entry.
  //
  // These lists used to be loaded by whichever button navigated to them — Nav's
  // tab, the match popup's "View Matches", the empty state's "Discover People".
  // With real URLs that is no longer sufficient: /discover and /matches can be
  // entered by a pasted link, a refresh or the back button, none of which press
  // a button. Loading is now a property of being on the route.
  //
  // Keyed on the user *id*, not the user object: `setUser` runs on every swipe
  // (it increments daily_swipes), and depending on identity would refetch the
  // whole list each time.
  // ---------------------------------------------------------------------------
  const userId = user?.id ?? null;

  useEffect(() => {
    if (userId && view === 'discover') fetchDiscoverUsers();
  }, [userId, view, fetchDiscoverUsers]);

  useEffect(() => {
    if (userId && view === 'matches') fetchMatches();
  }, [userId, view, fetchMatches]);

  const passwordResetEl = (
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

  const registerEl = (
    <RegisterView
      email={email} setEmail={setEmail}
      password={password} setPassword={setPassword}
      error={error} loading={loading}
      handleRegister={handleRegister} setView={setView}
    />
  );

  const loginEl = (
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

  const discoverEl = (
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
          swipeLimitReached={swipeLimitReached}
          swipesRemaining={swipesRemaining}
          swipesResetAt={user?.swipes_reset_at}
          handleSwipe={handleSwipe}
          handleUndo={handleUndo}
          handleBlock={handleBlock}
          handleOpenReport={handleOpenReport}
          fetchDiscoverUsers={fetchDiscoverUsers}
          setView={setView}
          navProps={navProps}
        />
        {reportModalEl}
      </>
  );

  const matchesEl = (
      <>
        <MatchesView
          matches={matches}
          matchesLoading={matchesLoading}
          matchesError={matchesError}
          fetchMatches={fetchMatches}
          openChat={openChat}
          user={user}
          setView={setView}
          handleOpenReport={handleOpenReport}
          navProps={navProps}
        />
        {reportModalEl}
      </>
  );

  const chatEl = (
      <>
        <ChatRoute
          matches={matches}
          matchesLoaded={matchesLoaded}
          currentMatch={currentMatch}
          onOpen={bindChat}
          chatProps={{
            messages,
            messagesLoading,
            messagesError,
            messageInput,
            setMessageInput,
            sending,
            sendError,
            sendMessage,
            loadMessages,
            hasMoreMessages,
            loadingMore,
            loadMoreMessages,
            handleDeleteMessage,
            typingUser,
            sendTypingEvent,
            handleUnmatch,
            handleBlock,
            handleBlockAndReport,
            handleOpenReport,
            setView,
          }}
        />
        {reportModalEl}
      </>
  );

  const profileEl = (
    <>
      <ProfileView
        user={user}
        avatarStatus={avatarStatus}
        isStale={isStale}
        isGenerating={isGenerating}
        name={name}
        age={age}
        location={location}
        bio={bio}
        error={error}
        loading={loading}
        copied={copied}
        handleSaveProfile={handleSaveProfile}
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

  const protect = (element) => (
    <RequireAuth user={user} booting={booting}>{element}</RequireAuth>
  );

  // A password-reset link lands on `/?token=…`; send it to the screen that can
  // use it. The token itself is already in state and has been stripped from the
  // URL, so it is not carried through the redirect.
  const indexEl = urlTokens.reset
    ? <Navigate to={PATHS.resetPassword} replace />
    : booting
      ? <Splash />
      : <Navigate to={user ? PATHS.profile : PATHS.login} replace />;

  return (
    <EmailVerificationProvider email={user?.email}>
      {/* Above the routes on purpose: whichever screen provoked the refusal,
          the explanation is in the same place and says the same thing. */}
      <EmailVerificationBanner />
      <Routes>
      <Route path="/" element={indexEl} />

      {/* Public, and deliberately stable: the mobile client deep-links to
          these two exact paths for the canonical legal text (GAPS #35). */}
      <Route path={PATHS.privacy} element={<LegalPage view="privacy" setView={setView} />} />
      <Route path={PATHS.terms} element={<LegalPage view="terms" setView={setView} />} />

      <Route path={PATHS.login} element={user ? <Navigate to={PATHS.profile} replace /> : loginEl} />
      <Route path={PATHS.register} element={registerEl} />
      <Route path={PATHS.forgotPassword} element={passwordResetEl} />
      <Route path={PATHS.resetPassword} element={passwordResetEl} />

      <Route path={PATHS.discover} element={protect(discoverEl)} />
      <Route path={PATHS.matches} element={protect(matchesEl)} />
      <Route path={PATHS.chat} element={protect(chatEl)} />
      <Route path={PATHS.profile} element={protect(profileEl)} />

      {/* Unknown path: hand it to the index route, which knows whether there is
          a session and therefore whether "home" is /profile or /login. */}
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </EmailVerificationProvider>
  );
}
