import { API_URL } from '../api/client';
import { ANIMAL_EMOJI, FALLBACK_ANIMAL_EMOJI } from '../shared/constants';

export function animalEmoji(animal: string | null | undefined): string {
  if (!animal) return FALLBACK_ANIMAL_EMOJI;
  return ANIMAL_EMOJI.get(animal.toLowerCase()) ?? FALLBACK_ANIMAL_EMOJI;
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
