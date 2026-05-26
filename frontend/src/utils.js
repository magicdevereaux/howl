// In development the Vite proxy forwards /api/* to the FastAPI backend so
// the browser always talks to the same origin (localhost:3000).  Use an
// empty string for API_URL so all requests are relative (no CORS needed).
// In production set VITE_API_URL to the full backend URL.
export const API_URL = import.meta.env.VITE_API_URL || '';

// Derive the WebSocket base URL from the current page origin in dev
// (the Vite proxy forwards WS connections too), or from VITE_API_URL in prod.
export const WS_URL = import.meta.env.VITE_API_URL
  ? import.meta.env.VITE_API_URL.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
  : `${typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws'}://${typeof window !== 'undefined' ? window.location.host : 'localhost:3000'}`;

const ANIMAL_EMOJI = {
  wolf: '🐺', fox: '🦊', deer: '🦌', bear: '🐻', owl: '🦉',
  cat: '🐱', lion: '🦁', otter: '🦦', eagle: '🦅', panther: '🐆',
  hawk: '🦅', rabbit: '🐰', dolphin: '🐬', crow: '🐦‍⬛',
};

export const animalEmoji = (animal) => ANIMAL_EMOJI[animal?.toLowerCase()] || '🐾';

// Resolve avatar URL: stored paths are server-relative (/avatars/…), full URLs are used as-is.
export const avatarUrl = (url) =>
  !url ? null : url.startsWith('http') ? url : `${API_URL}${url}`;
