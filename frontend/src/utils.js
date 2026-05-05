export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';

const ANIMAL_EMOJI = {
  wolf: '🐺', fox: '🦊', deer: '🦌', bear: '🐻', owl: '🦉',
  cat: '🐱', lion: '🦁', otter: '🦦', eagle: '🦅', panther: '🐆',
  hawk: '🦅', rabbit: '🐰', dolphin: '🐬', crow: '🐦‍⬛',
};

export const animalEmoji = (animal) => ANIMAL_EMOJI[animal?.toLowerCase()] || '🐾';

// Resolve avatar URL: stored paths are server-relative (/avatars/…), full URLs are used as-is.
export const avatarUrl = (url) =>
  !url ? null : url.startsWith('http') ? url : `${API_URL}${url}`;
