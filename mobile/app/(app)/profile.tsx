import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { api } from '../../src/api/client';
import { useAuth, User } from '../../src/auth/AuthContext';
import { colors as C } from '../../src/theme';
import { animalEmoji, capitalise, resolveAvatarUrl } from '../../src/utils/avatar';

interface AvatarStatus {
  avatar_status: 'pending' | 'generating' | 'ready' | 'failed' | null;
  animal: string | null;
  avatar_url: string | null;
  avatar_description: string | null;
  personality_traits: string[] | null;
}

interface ProfileDraft {
  name: string;
  age: string;
  location: string;
  bio: string;
}

const GENERATING_STATUSES = new Set(['pending', 'generating']);

export default function ProfileScreen() {
  const { user, logout, updateUser } = useAuth();

  const [avatarStatus, setAvatarStatus] = useState<AvatarStatus | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(true);
  const [avatarImgError, setAvatarImgError] = useState(false);

  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>({ name: '', age: '', location: '', bio: '' });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Avatar status ─────────────────────────────────────────────────────────

  const fetchAvatarStatus = async () => {
    const res = await api<AvatarStatus>('/api/avatar/status');
    if (res.ok) setAvatarStatus(res.data);
    setAvatarLoading(false);
  };

  useEffect(() => {
    fetchAvatarStatus();
  }, []);

  // Poll while avatar is generating.
  // Depending on avatarStatus?.avatar_status (rather than avatarStatus
  // itself) is deliberate: it's the only field that decides whether we
  // start/stop the interval, and it already captures every transition that
  // matters, including avatarStatus going from null to a real object.
  // Depending on the whole object would re-run this effect (clearing and
  // resetting the interval) on every 3s poll tick even while status is
  // unchanged, since fetchAvatarStatus produces a new object each time.
  useEffect(() => {
    if (avatarStatus && GENERATING_STATUSES.has(avatarStatus.avatar_status ?? '')) {
      pollRef.current = setInterval(fetchAvatarStatus, 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avatarStatus?.avatar_status]);

  // ── Edit mode ─────────────────────────────────────────────────────────────

  const enterEdit = () => {
    setDraft({
      name:     user?.name     ?? '',
      age:      user?.age != null ? String(user.age) : '',
      location: user?.location ?? '',
      bio:      user?.bio      ?? '',
    });
    setSaveError(null);
    setIsEditing(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);

    const body: Record<string, unknown> = {
      name:     draft.name.trim()     || null,
      location: draft.location.trim() || null,
      bio:      draft.bio.trim()      || null,
    };
    const age = parseInt(draft.age, 10);
    body.age = isNaN(age) ? null : age;

    const res = await api<User>('/api/profile/me', {
      method: 'PATCH',
      body: JSON.stringify(body),
    });

    setSaving(false);

    if (!res.ok) {
      setSaveError(res.error);
      return;
    }

    if (res.data) updateUser(res.data);
    setIsEditing(false);

    // Refetch avatar status in case the bio change triggered a regen
    setAvatarImgError(false);
    fetchAvatarStatus();
  };

  // ── Avatar render helpers ─────────────────────────────────────────────────

  const resolvedUrl = resolveAvatarUrl(avatarStatus?.avatar_url ?? user?.avatar_url);
  const isReady     = avatarStatus?.avatar_status === 'ready';
  const isGenerating = GENERATING_STATUSES.has(avatarStatus?.avatar_status ?? '');
  const animal      = avatarStatus?.animal ?? user?.animal;

  const renderAvatar = () => {
    if (avatarLoading) return <ActivityIndicator color={C.gold} size="large" />;

    if (isReady && resolvedUrl && !avatarImgError) {
      return (
        <Image
          source={{ uri: resolvedUrl }}
          style={styles.avatarImg}
          onError={() => setAvatarImgError(true)}
        />
      );
    }

    return (
      <Text style={styles.avatarEmoji}>{animalEmoji(animal)}</Text>
    );
  };

  const renderStatusText = () => {
    if (avatarLoading)   return null;
    if (isGenerating)    return <Text style={styles.statusSub}>Claude is analysing your bio…</Text>;
    if (!user?.bio)      return <Text style={styles.statusSub}>Add a bio to reveal your spirit animal</Text>;
    if (avatarStatus?.avatar_status === 'failed') return <Text style={[styles.statusSub, { color: C.errorLight }]}>Generation failed — try saving an updated bio</Text>;
    return null;
  };

  // ── Render ────────────────────────────────────────────────────────────────

  if (!user) return null;

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: C.bg }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >

        {/* ── Spirit animal hero ─────────────────────────────────────────── */}
        <View style={styles.heroCard}>
          <View style={styles.avatarWrap}>{renderAvatar()}</View>

          {isGenerating && (
            <View style={styles.progressBar}>
              <View style={styles.progressFill} />
            </View>
          )}

          {isReady && animal && (
            <>
              <Text style={styles.animalLabel}>Your spirit animal</Text>
              <Text style={styles.animalName}>{capitalise(animal)}</Text>
            </>
          )}

          {renderStatusText()}

          {/* Personality traits */}
          {isReady && (avatarStatus?.personality_traits?.length ?? 0) > 0 && (
            <View style={styles.traitRow}>
              {(avatarStatus!.personality_traits!).map((t, i) => (
                <View key={i} style={styles.traitPill}>
                  <Text style={styles.traitText}>{t}</Text>
                </View>
              ))}
            </View>
          )}

          {/* Spirit animal description */}
          {isReady && avatarStatus?.avatar_description && (
            <Text style={styles.avatarDesc}>{avatarStatus.avatar_description}</Text>
          )}
        </View>

        {/* ── Profile card ───────────────────────────────────────────────── */}
        <View style={styles.profileCard}>
          <View style={styles.cardHeader}>
            <Text style={styles.cardTitle} accessibilityRole="header">
              {isEditing ? 'Edit Profile' : 'Your Profile'}
            </Text>
            {!isEditing && (
              <Pressable
                style={styles.editBtn}
                onPress={enterEdit}
                accessibilityRole="button"
                accessibilityLabel="Edit your profile"
              >
                <Text style={styles.editBtnText}>Edit</Text>
              </Pressable>
            )}
          </View>

          <Text style={styles.emailChip}>{user.email}</Text>

          {saveError && (
            <View
              style={styles.errorBox}
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
            >
              <Text style={styles.errorText}>{saveError}</Text>
            </View>
          )}

          {!isEditing ? (
            /* Read-only view */
            <View style={styles.fields}>
              <Field label="Name"     value={user.name} />
              <Field label="Age"      value={user.age != null ? String(user.age) : null} />
              <Field label="Location" value={user.location} />
              <Field label="Bio"      value={user.bio} multiline />
            </View>
          ) : (
            /* Edit form */
            <View>
              <FormField label="Name">
                <TextInput
                  style={styles.input}
                  value={draft.name}
                  onChangeText={(v) => setDraft((d) => ({ ...d, name: v }))}
                  placeholder="Your first name"
                  placeholderTextColor={C.textDisabled}
                  maxLength={100}
                />
              </FormField>

              <FormField label="Age">
                <TextInput
                  style={styles.input}
                  value={draft.age}
                  onChangeText={(v) => setDraft((d) => ({ ...d, age: v }))}
                  placeholder="25"
                  placeholderTextColor={C.textDisabled}
                  keyboardType="number-pad"
                  maxLength={3}
                />
              </FormField>

              <FormField label="Location">
                <TextInput
                  style={styles.input}
                  value={draft.location}
                  onChangeText={(v) => setDraft((d) => ({ ...d, location: v }))}
                  placeholder="City, State"
                  placeholderTextColor={C.textDisabled}
                  maxLength={100}
                />
              </FormField>

              <FormField label="Bio">
                <TextInput
                  style={[styles.input, styles.bioInput]}
                  value={draft.bio}
                  onChangeText={(v) => setDraft((d) => ({ ...d, bio: v }))}
                  placeholder="Write about yourself…"
                  placeholderTextColor={C.textDisabled}
                  multiline
                  maxLength={500}
                />
                <Text style={styles.charCount}>{draft.bio.length}/500</Text>
              </FormField>

              <Text style={styles.regenHint}>
                Saving a changed bio will auto-regenerate your spirit animal if a slot is available.
              </Text>

              <View style={styles.editActions}>
                <Pressable
                  style={[styles.btn, styles.cancelBtn]}
                  onPress={() => setIsEditing(false)}
                  disabled={saving}
                  accessibilityRole="button"
                  accessibilityLabel="Discard changes"
                  accessibilityState={{ disabled: saving }}
                >
                  <Text style={styles.cancelBtnText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[styles.btn, styles.saveBtn, saving && styles.btnDisabled]}
                  onPress={handleSave}
                  disabled={saving}
                  accessibilityRole="button"
                  accessibilityLabel={saving ? 'Saving changes' : 'Save changes'}
                  accessibilityHint="Changing your bio may regenerate your spirit animal"
                  accessibilityState={{ busy: saving, disabled: saving }}
                >
                  {saving
                    ? <ActivityIndicator color={C.text} size="small" />
                    : <Text style={styles.saveBtnText}>Save Changes</Text>
                  }
                </Pressable>
              </View>
            </View>
          )}
        </View>

        {/* ── Logout ─────────────────────────────────────────────────────── */}
        <Pressable
          style={styles.logoutBtn}
          onPress={logout}
          accessibilityRole="button"
          accessibilityLabel="Sign out of Howl"
        >
          <Text style={styles.logoutText}>Sign Out</Text>
        </Pressable>

      </ScrollView>
    </KeyboardAvoidingView>
  );
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function Field({ label, value, multiline }: { label: string; value: string | null | undefined; multiline?: boolean }) {
  return (
    <View style={fieldStyles.wrap}>
      <Text style={fieldStyles.label}>{label}</Text>
      <Text style={[fieldStyles.value, !value && fieldStyles.empty, multiline && { lineHeight: 22 }]}>
        {value || '—'}
      </Text>
    </View>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  // The label element gets a stable nativeID and each input points at it with
  // accessibilityLabelledBy, so a screen reader announces "Name, text field"
  // instead of reading an unlabelled box.
  const labelId = `profile-field-${label.toLowerCase().replace(/\s+/g, '-')}`;
  return (
    <View style={{ marginBottom: 4 }}>
      <Text style={styles.formLabel} nativeID={labelId}>{label}</Text>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
            accessibilityLabel: label,
            accessibilityLabelledBy: labelId,
          })
        : children}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  scroll:        { flex: 1, backgroundColor: C.bg },
  scrollContent: { padding: 16, paddingBottom: 40 },

  // Hero card
  heroCard: {
    backgroundColor: C.bgCard,
    borderRadius: 20,
    padding: 24,
    alignItems: 'center',
    marginBottom: 16,
    shadowColor: '#000',
    shadowOpacity: 0.4,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 8 },
    elevation: 8,
  },
  avatarWrap: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: C.bgHover,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
    overflow: 'hidden',
    borderWidth: 2,
    borderColor: C.border,
  },
  avatarImg: {
    width: 120,
    height: 120,
    borderRadius: 60,
  },
  avatarEmoji: {
    fontSize: 60,
    lineHeight: 70,
  },
  progressBar: {
    height: 3,
    width: '80%',
    backgroundColor: C.bgHover,
    borderRadius: 2,
    overflow: 'hidden',
    marginBottom: 12,
  },
  progressFill: {
    height: 3,
    width: '55%',
    backgroundColor: C.accentHover,
    borderRadius: 2,
  },
  animalLabel: {
    fontSize: 13,
    color: C.textSec,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  animalName: {
    fontSize: 28,
    fontWeight: '500',
    color: C.gold,
    fontStyle: 'italic',
    marginBottom: 12,
  },
  statusSub: {
    fontSize: 13,
    color: C.textSec,
    fontStyle: 'italic',
    textAlign: 'center',
    marginBottom: 4,
  },
  traitRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 8,
    marginTop: 4,
    marginBottom: 12,
  },
  traitPill: {
    backgroundColor: C.bgHover,
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  traitText: {
    color: C.textSec,
    fontSize: 13,
    fontStyle: 'italic',
  },
  avatarDesc: {
    fontSize: 13,
    color: C.textSec,
    fontStyle: 'italic',
    textAlign: 'center',
    lineHeight: 20,
    marginTop: 8,
    paddingHorizontal: 8,
  },

  // Profile card
  profileCard: {
    backgroundColor: C.bgCard,
    borderRadius: 16,
    padding: 24,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOpacity: 0.3,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: C.text,
  },
  editBtn: {
    backgroundColor: C.accent,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 7,
  },
  editBtnText: {
    color: C.text,
    fontSize: 13,
    fontWeight: '600',
  },
  emailChip: {
    fontSize: 12,
    color: C.textDisabled,
    backgroundColor: C.bgInput,
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 10,
    marginBottom: 16,
  },
  errorBox: {
    backgroundColor: 'rgba(197,48,48,0.15)',
    borderColor: 'rgba(197,48,48,0.4)',
    borderWidth: 1,
    borderRadius: 8,
    padding: 10,
    marginBottom: 12,
  },
  errorText: {
    color: C.errorLight,
    fontSize: 13,
    textAlign: 'center',
  },
  fields: { gap: 16 },

  // Edit form
  formLabel: {
    color: C.textSec,
    fontSize: 13,
    fontWeight: '500',
    marginBottom: 6,
    marginTop: 8,
  },
  input: {
    backgroundColor: C.bgInput,
    borderColor: C.border,
    borderWidth: 1.5,
    borderRadius: 10,
    color: C.text,
    fontSize: 15,
    paddingHorizontal: 14,
    paddingVertical: Platform.OS === 'ios' ? 13 : 10,
    marginBottom: 4,
  },
  bioInput: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  charCount: {
    color: C.textDisabled,
    fontSize: 11,
    textAlign: 'right',
    marginBottom: 8,
  },
  regenHint: {
    color: C.textDisabled,
    fontSize: 12,
    fontStyle: 'italic',
    marginBottom: 16,
  },
  editActions: {
    flexDirection: 'row',
    gap: 10,
  },
  btn: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: 'center',
  },
  cancelBtn: {
    backgroundColor: C.bgHover,
    borderWidth: 1,
    borderColor: C.border,
  },
  cancelBtnText: {
    color: C.textSurface,
    fontSize: 15,
    fontWeight: '600',
  },
  saveBtn: {
    flex: 2,
    backgroundColor: C.accent,
  },
  saveBtnText: {
    color: C.text,
    fontSize: 15,
    fontWeight: '700',
  },
  btnDisabled: { opacity: 0.6 },

  // Logout
  logoutBtn: {
    alignItems: 'center',
    paddingVertical: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: C.border,
    marginBottom: 8,
  },
  logoutText: {
    color: C.textSec,
    fontSize: 15,
    fontWeight: '500',
  },
});

const fieldStyles = StyleSheet.create({
  wrap:  { gap: 4 },
  label: { fontSize: 11, fontWeight: '600', color: C.textDisabled, textTransform: 'uppercase', letterSpacing: 0.5 },
  value: { fontSize: 15, color: C.textSurface, lineHeight: 21 },
  empty: { color: C.textDisabled, fontStyle: 'italic' },
});
