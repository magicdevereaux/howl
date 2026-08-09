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
import { ChatProvider } from './contexts/ChatContext';
import { DiscoverProvider } from './contexts/DiscoverContext';
import { EmailVerificationProvider } from './contexts/EmailVerificationContext';
import { ReportProvider } from './contexts/ReportContext';
import { SessionProvider } from './contexts/SessionContext';
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
  // Everything the server has told us about the daily swipe quota, or null.
  //
  // The quota is a server rule: `_DAILY_SWIPE_LIMIT` in app/api/swipes.py is
  // the only authority, and a conditional UPDATE enforces it regardless of what
  // any client believes. `UserOut` does not carry the number, so until the
  // server refuses a swipe the client genuinely does not know it — and the
  // honest representation of "don't know" is null, not 20.
  //
  // It used to be seeded with a hardcoded 20 (GAPS #32), which the client then
  // used to grey out swiping on its own. Two ways for that to be wrong: raise
  // the server limit and the client locks users out early with a message
  // stating the old number; lower it and the client promises swipes the server
  // will refuse. Now the server's 429 supplies the limit, the wording and the
  // reset time together, and nothing is displayed before it arrives.
  const [swipeQuota, setSwipeQuota] = useState(null);
  const [currentMatch, setCurrentMatch] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState('');
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // No `messageInput` here any more. It was the single worst piece of state in
  // this component: text on the root meant every keystroke re-rendered the
  // entire tree (GAPS #33). MessageComposer owns it now.
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const [typingUser, setTypingUser] = useState(null); // display name of who's typing
  // Set when the match is unmatched or blocked away mid-session (GAPS-ROUND-2
  // #60). Per conversation, so it is cleared alongside hasConnectedRef below.
  const [matchClosed, setMatchClosed] = useState(false);

  const chatWsRef = useRef(null);       // holds the live WebSocket for sending
  const typingTimerRef = useRef(null);  // auto-clears the typing indicator
  // Whether this conversation's socket has opened before. Distinguishes the
  // first connect (history was just loaded) from a reconnect (it may be stale).
  const hasConnectedRef = useRef(false);
  // The match id `loadMessages` currently has in flight, or null. A flapping
  // connection reconnects (and therefore refetches) on every brief open, and
  // without this a slow response plus a fast flap queues up a second request
  // for the same match before the first has answered — a reconnect storm
  // turning into a refetch storm (GAPS-ROUND-2 #47).
  const loadingMatchIdRef = useRef(null);
  const [emailNotifications, setEmailNotifications] = useState(true);
  // Reporting moved out entirely — three useStates and two handlers now live in
  // ReportProvider, which also renders the dialog. The delete-account modal's
  // open flag and confirmation text moved into ProfileView, the only screen that
  // opens it.
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
    // Skip a re-entrant call for the same match: see loadingMatchIdRef above.
    if (loadingMatchIdRef.current === matchId) return;
    loadingMatchIdRef.current = matchId;
    setMessagesLoading(true);
    setMessagesError('');
    try {
      const res = await apiFetch(`/api/matches/${matchId}/messages`, {

      });
      if (res.ok) {
        const data = await res.json();
        // Merge by id rather than replace (GAPS-ROUND-2 #47). This is called
        // both to open a conversation (messages was just cleared, so a merge
        // is a no-op difference from a replace) and to refetch on WS
        // reconnect — where a replace would silently discard whatever
        // `loadMoreMessages` had already paged in, since this endpoint only
        // ever returns the latest page, and would drop a message delivered
        // over the socket a moment after this request was sent but before it
        // resolved.
        setMessages((prev) => {
          const byId = new Map(prev.map((m) => [m.id, m]));
          for (const m of data.messages) byId.set(m.id, m);
          return Array.from(byId.values()).sort((a, b) => a.id - b.id);
        });
        setHasMoreMessages(data.has_more);
      } else {
        setMessagesError("Couldn't load messages.");
      }
    } catch {
      setMessagesError('Network error — check your connection.');
    } finally {
      setMessagesLoading(false);
      // Only clear our own claim: if the user switched matches while this
      // call was in flight, a newer call for the new match id already holds
      // the ref, and clearing it here would let a stray reconnect for that
      // match slip past the guard.
      if (loadingMatchIdRef.current === matchId) loadingMatchIdRef.current = null;
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
    setMatchClosed(false);

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
          } else if (type === 'messages_read') {
            // GAPS-ROUND-2 #49. A high-water mark, not a per-message event, so a
            // dropped receipt is repaired by the next one rather than lost. The
            // server marked every message in the match the reader did *not*
            // send, so from here that means "our own messages up to this id".
            //
            // The frame also reaches the reader's own sockets, which is how a
            // second tab clears its badge — but that copy must not be applied
            // here, or the reader would see ✓✓ on messages the other party
            // hasn't looked at.
            const { reader_id: readerId, last_read_message_id: upTo, read_at: readAt } = data;
            if (typeof upTo === 'number' && readerId !== user?.id) {
              setMessages((prev) => {
                let changed = false;
                const next = prev.map((m) => {
                  if (m.is_mine && m.id <= upTo && !m.read_at) {
                    changed = true;
                    return { ...m, read_at: readAt };
                  }
                  return m;
                });
                return changed ? next : prev;
              });
            }
          } else if (type === 'match_closed') {
            // The match was unmatched or blocked away from under us (#60). The
            // server closes with 4003 right after this frame, and that close is
            // already terminal, so all this has to do is stop the user typing
            // into a conversation that no longer exists.
            setMatchClosed(true);
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
    // `user?.id` is read by the messages_read handler to tell our own echoed
    // receipt from the other party's. It is stable for the life of a session,
    // so listing it costs nothing — but leaving it out would mean a socket
    // opened before the profile fetch resolved kept comparing against
    // `undefined` and applied the reader's own receipt to their own messages.
  }, [view, currentMatchId, loadMessages, user?.id]);

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
        // The dialog's open flag and confirmation text belong to ProfileView
        // now, and navigating away unmounts it — so there is nothing to reset.
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

  // useCallback because MessageList is memoized and takes this as a prop: a new
  // function identity each render would defeat the memo entirely.
  const handleDeleteMessage = useCallback(async (messageId) => {
    if (!currentMatchId) return;
    try {
      const res = await apiFetch(
        `/api/matches/${currentMatchId}/messages/${messageId}`,
        { method: 'DELETE', credentials: 'include' },
      );
      if (res.ok) {
        const updated = await res.json();
        setMessages((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      }
    } catch (err) {
      console.error('Failed to delete message', err);
    }
  }, [currentMatchId]);

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

  /**
   * Send a message. Returns whether it was accepted.
   *
   * Takes the text as an argument rather than reading it from state: the text
   * belongs to MessageComposer now, which is what stopped every keystroke from
   * re-rendering the app (GAPS #33). The boolean is how the composer knows
   * whether to clear the field — it keeps what you typed on any failure.
   */
  const sendMessage = useCallback(async (content) => {
    if (!content || !currentMatchId || sending) return false;
    setSending(true);
    setSendError('');
    try {
      const res = await apiFetch(`/api/matches/${currentMatchId}/messages`, {
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
        return true;
      }
      // Stay quiet about *why* when the global verification notice is already
      // saying it: "Message failed to send — please try again" next to "verify
      // your email" reads as two unrelated faults, and "try again" is advice
      // that cannot work.
      if (!isVerificationBlocked(res)) {
        setSendError("Message failed to send — please try again.");
      }
      return false;
    } catch {
      setSendError('Network error — message not sent.');
      return false;
    } finally {
      setSending(false);
    }
  }, [currentMatchId, sending]);

  // Stable identity so the memoized composer is not re-rendered by a new
  // callback on every parent render.
  const sendTypingEvent = useCallback(() => {
    const ws = chatWsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'typing' }));
    }
  }, []);

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

  // useCallback, and load-bearing: ProfileView calls this from an effect that
  // lists it as a dependency. As a plain function it was a new identity every
  // render, so the effect re-ran, set state, re-rendered, and re-ran — an
  // infinite loop. That is exactly the trap the DiscoverView filter effect fell
  // into, and the reason the eslint-disable that used to sit on ProfileView's
  // effect was hiding a real hazard rather than a false positive.
  const fetchBlocks = useCallback(async () => {
    setBlocksLoading(true);
    try {
      const res = await apiFetch(`/api/blocks`, {

      });
      if (res.ok) setBlocks(await res.json());
    } catch (err) {
      console.error('Failed to load blocked users', err);
    } finally {
      setBlocksLoading(false);
    }
  }, []);

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
        // The one moment the server states the rule. Take all of it — the
        // number, its own wording, and the reset time it computed — rather than
        // keeping a second copy of any of them here.
        const limit = Number(data.detail.limit);
        setSwipeQuota({
          limit: Number.isFinite(limit) && limit > 0 ? limit : null,
          message: data.detail.message || null,
          resetsAt: data.detail.resets_at || null,
        });
        return;
      }

      // Only mutate the deck and arm Undo once a swipe row is known to exist.
      // GAPS-ROUND-2 #50: this used to run unconditionally, so a 500/409 both
      // discarded a card that was never recorded *and* left Undo pointing at
      // the previous, successful swipe — `DELETE /api/swipes/last` deletes the
      // most recent actual row, which on a failure is someone else's match.
      // Addressed by id, not position: `discoverUsers` can be replaced
      // wholesale by a refetch (nav revisit) between this request firing and
      // its response landing, and a positional `slice(1)` would then remove
      // whichever profile now sits at index 0 rather than the one the user
      // actually swiped on.
      if (res.ok) {
        setDiscoverUsers(prev => prev.filter(u => u.id !== targetUserId));
        setCanUndo(true);
        if (data.matched) {
          setMatchPopup(data.match);
        }
        setUser(prev => prev ? { ...prev, daily_swipes: (prev.daily_swipes || 0) + 1 } : prev);
      } else {
        // Leave the card in place — "tap to try again" only makes sense if
        // there is still something to tap on.
        setSwipeError('Swipe failed — tap to try again.');
        setTimeout(() => setSwipeError(''), 4000);
      }
    } catch {
      // Same contract as the res.ok === false branch above: the request may
      // never have reached the server, so the card stays and Undo stays
      // unarmed.
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
  // Data on route entry.
  //
  // These lists used to be loaded by whichever button navigated to them â€” Nav's
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

  // ---------------------------------------------------------------------------
  // Context values.
  //
  // This is what replaced the prop drilling GAPS #33 describes: ProfileView took
  // 24 props, DiscoverView 24 and ChatView 21, nearly all of them threaded from
  // here because here is where the state lives. All four screens now take none.
  //
  // Three values rather than one, split by what changes together: a swipe should
  // not invalidate the value the chat reads, and a message arriving should not
  // invalidate the profile's. See contexts/SessionContext.jsx for the note on
  // why these are plain objects rather than useMemo'd.
  // ---------------------------------------------------------------------------
  const totalUnread = matches.reduce((sum, m) => sum + (m.unread_count || 0), 0);

  const session = {
    user,
    avatarStatus,
    isStale,
    isGenerating,
    name, age, location, bio,
    error, loading, copied,
    emailNotifications,
    matches, matchesLoading, matchesError, totalUnread,
    blocks, blocksLoading,
    deleteLoading, deleteError,
    fetchMatches,
    openChat,
    logout: handleLogout,
    handleSaveProfile,
    handleRegenerate,
    handleCopyAnimal,
    handleToggleNotifications,
    handleDeleteAccount,
    setDeleteError,
    fetchBlocks,
    handleUnblock,
  };

  const discover = {
    discoverUsers, discoverLoading, discoverError, fetchDiscoverUsers,
    swipeLoading, swipeError, canUndo, undoMessage,
    matchPopup, setMatchPopup,
    preferenceFilters: { lookingFor, gender, sexuality, agePrefMin, agePrefMax },
    handleSaveFilters,
    // "Out of swipes" is now something the server has said, not something the
    // client worked out. Premium accounts are unlimited and never see either.
    swipeLimitReached: !user?.is_premium && !!swipeQuota,
    swipesRemaining:
      user?.is_premium || !swipeQuota?.limit
        ? null
        : Math.max(0, swipeQuota.limit - (user?.daily_swipes || 0)),
    swipesUsed: user?.is_premium ? null : user?.daily_swipes || 0,
    limitMessage: swipeQuota?.message,
    limitResetsAt: swipeQuota?.resetsAt,
    handleSwipe, handleUndo, handleBlock,
  };

  const chat = {
    currentMatch,
    messages, messagesLoading, messagesError, loadMessages,
    sending, sendError, sendMessage, sendTypingEvent,
    hasMoreMessages, loadingMore, loadMoreMessages, handleDeleteMessage,
    typingUser, matchClosed,
    handleUnmatch, handleBlock, handleBlockAndReport,
  };

  // ---------------------------------------------------------------------------
  // Route table â€” see src/routes/paths.js
  // ---------------------------------------------------------------------------

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

  const credentialsProps = {
    email, setEmail, password, setPassword, error, loading, setView,
  };

  const protect = (element) => (
    <RequireAuth user={user} booting={booting}>{element}</RequireAuth>
  );

  // A password-reset link lands on `/?token=â€¦`; send it to the screen that can
  // use it. The token itself is already in state and has been stripped from the
  // URL, so it is not carried through the redirect.
  const indexEl = urlTokens.reset
    ? <Navigate to={PATHS.resetPassword} replace />
    : booting
      ? <Splash />
      : <Navigate to={user ? PATHS.profile : PATHS.login} replace />;

  return (
    <SessionProvider value={session}>
      <EmailVerificationProvider email={user?.email}>
        <ReportProvider>
          {/* Above the routes on purpose: whichever screen provoked the
              refusal, the explanation is in the same place and says the same
              thing. */}
          <EmailVerificationBanner />

          <Routes>
            <Route path="/" element={indexEl} />

            {/* Public, and deliberately stable: the mobile client deep-links to
                these two exact paths for the canonical legal text (GAPS #35). */}
            <Route path={PATHS.privacy} element={<LegalPage view="privacy" setView={setView} />} />
            <Route path={PATHS.terms} element={<LegalPage view="terms" setView={setView} />} />

            <Route
              path={PATHS.login}
              element={user
                ? <Navigate to={PATHS.profile} replace />
                : (
                  <LoginView
                    {...credentialsProps}
                    handleLogin={handleLogin}
                    setForgotEmail={setForgotEmail}
                    setForgotDone={setForgotDone}
                    setError={setError}
                  />
                )}
            />
            <Route
              path={PATHS.register}
              element={<RegisterView {...credentialsProps} handleRegister={handleRegister} />}
            />
            <Route path={PATHS.forgotPassword} element={passwordResetEl} />
            <Route path={PATHS.resetPassword} element={passwordResetEl} />

            <Route
              path={PATHS.discover}
              element={protect(
                <DiscoverProvider value={discover}>
                  <DiscoverView />
                </DiscoverProvider>,
              )}
            />
            <Route path={PATHS.matches} element={protect(<MatchesView />)} />
            <Route
              path={PATHS.chat}
              element={protect(
                <ChatProvider value={chat}>
                  <ChatRoute
                    matches={matches}
                    matchesLoaded={matchesLoaded}
                    currentMatch={currentMatch}
                    onOpen={bindChat}
                  />
                </ChatProvider>,
              )}
            />
            <Route path={PATHS.profile} element={protect(<ProfileView />)} />

            {/* Unknown path: hand it to the index route, which knows whether
                there is a session and therefore whether "home" is /profile or
                /login. */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ReportProvider>
      </EmailVerificationProvider>
    </SessionProvider>
  );
}
