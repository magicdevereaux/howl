import { API_URL } from '../api/client';

const EMOJI: Record<string, string> = {
  wolf: '🐺', fox: '🦊', bear: '🐻', owl: '🦉', otter: '🦦',
  eagle: '🦅', lion: '🦁', deer: '🦌', panther: '🐆', dolphin: '🐬',
  hawk: '🦅', crow: '🐦', cat: '🐱', elephant: '🐘', tiger: '🐯',
  salmon: '🐟', coyote: '🐺', hummingbird: '🐦', raven: '🐦', lynx: '🐱',
};

export function animalEmoji(animal: string | null | undefined): string {
  if (!animal) return '🐾';
  return EMOJI[animal.toLowerCase()] ?? '🐾';
}

/**
 * Resolve an avatar URL from the backend.
 * - Full https:// → R2 URL, use as-is.
 * - Server-relative path → prefix with API_URL.
 * - null / undefined → null (caller shows emoji fallback).
 */
export function resolveAvatarUrl(avatarUrl: string | null | undefined): string | null {
  if (!avatarUrl) return null;
  if (avatarUrl.startsWith('http')) return avatarUrl;
  return `${API_URL}${avatarUrl}`;
}

export function capitalise(s: string | null | undefined): string {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1);
}
