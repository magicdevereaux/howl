import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

import { api } from '../../src/api/client';
import { useAuth } from '../../src/auth/AuthContext';
import { colors as C } from '../../src/theme';
import { animalEmoji, capitalise, resolveAvatarUrl } from '../../src/utils/avatar';

// ── Types ────────────────────────────────────────────────────────────────────

interface DiscoverUser {
  id: number;
  name: string | null;
  age: number | null;
  location: string | null;
  bio: string | null;
  animal: string | null;
  avatar_url: string | null;
  personality_traits: string[] | null;
  avatar_description: string | null;
}

interface MatchInfo {
  id: number;
  other_user: { id: number; name: string | null; animal: string | null };
}

// ── Constants ────────────────────────────────────────────────────────────────

const SWIPE_THRESHOLD = 100; // px to commit
const SPRING_OUT = { damping: 28, stiffness: 200 } as const;
const SPRING_BACK = { damping: 20, stiffness: 300 } as const;

// ── Component ────────────────────────────────────────────────────────────────

export default function DiscoverScreen() {
  const { user } = useAuth();

  const [users, setUsers] = useState<DiscoverUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [swipeError, setSwipeError] = useState<string | null>(null);
  const [matchPopup, setMatchPopup] = useState<MatchInfo | null>(null);
  const [swiping, setSwiping] = useState(false);
  const [lastSwiped, setLastSwiped] = useState<DiscoverUser | null>(null);
  const [undoing, setUndoing] = useState(false);

  // Shared animation values
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  // Store current top user ID in a shared value so the worklet can read it
  // without a stale JS closure.
  const topUserIdShared = useSharedValue(0);

  useEffect(() => {
    topUserIdShared.value = users[0]?.id ?? 0;
    // topUserIdShared is a Reanimated shared value — its identity never
    // changes across renders, so including it is a no-op for reactivity.
    // Added anyway to keep the deps list exhaustive and lint clean.
  }, [users, topUserIdShared]);

  // ── Data ──────────────────────────────────────────────────────────────────

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setSwipeError(null);
    const res = await api<DiscoverUser[]>('/api/users/discover');
    setLoading(false);
    if (res.ok) setUsers(res.data);
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  // ── Swipe action ──────────────────────────────────────────────────────────

  const onSwipe = useCallback(async (userId: number, direction: 'like' | 'pass') => {
    if (!userId) return;
    setSwiping(true);
    setSwipeError(null);
    setLastSwiped(null); // clear previous undo opportunity on each new swipe

    // Capture the top user before advancing for undo
    let swipedUser: DiscoverUser | null = null;
    setUsers((prev) => {
      swipedUser = prev[0] ?? null;
      return prev.slice(1);
    });
    translateX.value = 0;
    translateY.value = 0;

    const res = await api<{ match?: MatchInfo | null }>(
      '/api/swipes',
      { method: 'POST', body: JSON.stringify({ target_user_id: userId, direction }) },
    );

    setSwiping(false);

    if (!res.ok) {
      if (res.status === 429) {
        setSwipeError("You've used all your swipes for today. Come back tomorrow!");
      } else {
        setSwipeError(res.error);
      }
      return;
    }

    if (res.data?.match) setMatchPopup(res.data.match);
    else if (swipedUser) setLastSwiped(swipedUser); // only offer undo when no match
    // translateX/translateY are Reanimated shared values with stable
    // identity — adding them doesn't change when onSwipe is recreated, but
    // keeps the deps list exhaustive.
  }, [translateX, translateY]);

  const handleUndo = useCallback(async () => {
    if (!lastSwiped || undoing) return;
    setUndoing(true);
    const res = await api('/api/swipes/last', { method: 'DELETE' });
    setUndoing(false);
    if (!res.ok) return;
    setUsers((prev) => [lastSwiped, ...prev]);
    setLastSwiped(null);
  }, [lastSwiped, undoing]);

  // ── Gesture ───────────────────────────────────────────────────────────────

  const panGesture = useMemo(
    () =>
      Gesture.Pan()
        .onUpdate((e) => {
          translateX.value = e.translationX;
          translateY.value = e.translationY * 0.25; // dampen vertical drift
        })
        .onEnd((e) => {
          if (e.translationX > SWIPE_THRESHOLD) {
            translateX.value = withSpring(600, SPRING_OUT, () =>
              runOnJS(onSwipe)(topUserIdShared.value, 'like'),
            );
          } else if (e.translationX < -SWIPE_THRESHOLD) {
            translateX.value = withSpring(-600, SPRING_OUT, () =>
              runOnJS(onSwipe)(topUserIdShared.value, 'pass'),
            );
          } else {
            translateX.value = withSpring(0, SPRING_BACK);
            translateY.value = withSpring(0, SPRING_BACK);
          }
        }),
    // translateX/translateY are stable-identity shared values (safe to omit).
    // topUserIdShared.value is read inside the .onEnd() worklet at gesture-end
    // time, not captured when this memo runs — it always sees the live value,
    // so it isn't a real dependency of the memo's *creation*. Adding it here
    // would instead recreate (and reattach) the Gesture object on every swipe,
    // which is the actual bug to avoid.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onSwipe],
  );

  // ── Animated styles ───────────────────────────────────────────────────────

  const cardStyle = useAnimatedStyle(() => {
    const rotate = interpolate(translateX.value, [-220, 0, 220], [-18, 0, 18]);
    return {
      transform: [
        { translateX: translateX.value },
        { translateY: translateY.value },
        { rotate: `${rotate}deg` },
      ],
    };
  });

  const likeStyle = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [0, SWIPE_THRESHOLD], [0, 1], Extrapolation.CLAMP),
  }));

  const passStyle = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [-SWIPE_THRESHOLD, 0], [1, 0], Extrapolation.CLAMP),
  }));

  // ── Tap-button swipes (accessible alternative to gesture) ─────────────────

  const tapSwipe = (direction: 'like' | 'pass') => {
    if (swiping || !users[0]) return;
    const target = 600 * (direction === 'like' ? 1 : -1);
    translateX.value = withSpring(target, SPRING_OUT, () =>
      runOnJS(onSwipe)(users[0].id, direction),
    );
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const topUser = users[0] ?? null;

  return (
    <View style={styles.shell}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Howl 🐺</Text>
        <Text style={styles.headerSub}>Discover</Text>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={C.accentHover} size="large" />
          <Text style={styles.centerText}>Finding spirit animals…</Text>
        </View>
      ) : !topUser ? (
        <View style={styles.center}>
          <Text style={styles.emptyEmoji} accessibilityElementsHidden importantForAccessibility="no">🎉</Text>
          <Text style={styles.emptyTitle} accessibilityRole="header">You've seen everyone!</Text>
          <Text style={styles.emptySub}>Check back later for new members.</Text>
          <Pressable
            style={styles.refreshBtn}
            onPress={fetchUsers}
            accessibilityRole="button"
            accessibilityLabel="Refresh the discover queue"
          >
            <Text style={styles.refreshBtnText}>Refresh</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.cardArea}>

          {/* Next card peek (depth illusion) */}
          {users[1] && (
            <View style={[styles.card, styles.cardBehind]} pointerEvents="none">
              <CardContent user={users[1]} />
            </View>
          )}

          {/* Active swipe card */}
          <GestureDetector gesture={panGesture}>
            <Animated.View style={[styles.card, cardStyle]} key={topUser.id}>
              {/* LIKE label */}
              <Animated.View style={[styles.swipeLabel, styles.likeLabel, likeStyle]}>
                <Text style={styles.likeLabelText}>LIKE</Text>
              </Animated.View>

              {/* PASS label */}
              <Animated.View style={[styles.swipeLabel, styles.passLabel, passStyle]}>
                <Text style={styles.passLabelText}>PASS</Text>
              </Animated.View>

              <CardContent user={topUser} />
            </Animated.View>
          </GestureDetector>

          {/* Swipe error */}
          {swipeError && (
            <View style={styles.errorBanner}>
              <Text style={styles.errorText}>{swipeError}</Text>
            </View>
          )}

          {/* Tap buttons */}
          <View style={styles.buttons}>
            <Pressable
              style={({ pressed }) => [styles.btn, styles.passBtn, pressed && styles.btnPressed]}
              onPress={() => tapSwipe('pass')}
              disabled={swiping}
              accessibilityRole="button"
              accessibilityLabel={`Pass on ${topUser.name || 'this person'}`}
              accessibilityHint="Removes them from your queue"
              accessibilityState={{ disabled: swiping, busy: swiping }}
            >
              {/* Decorative: the label above carries the meaning. */}
              <Text style={styles.btnEmoji} accessibilityElementsHidden importantForAccessibility="no">✕</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [styles.btn, styles.likeBtn, pressed && styles.btnPressed]}
              onPress={() => tapSwipe('like')}
              disabled={swiping}
              accessibilityRole="button"
              accessibilityLabel={`Like ${topUser.name || 'this person'}`}
              accessibilityHint="You match if they like you back"
              accessibilityState={{ disabled: swiping, busy: swiping }}
            >
              <Text style={styles.btnEmoji} accessibilityElementsHidden importantForAccessibility="no">❤️</Text>
            </Pressable>
          </View>

          {/* Undo last swipe */}
          <View style={styles.undoRow}>
            {lastSwiped && !swiping ? (
              <Pressable
                onPress={handleUndo}
                disabled={undoing}
                style={styles.undoBtn}
                accessibilityRole="button"
                accessibilityLabel={undoing ? 'Undoing last swipe' : 'Undo last swipe'}
                accessibilityState={{ disabled: undoing, busy: undoing }}
              >
                <Text style={styles.undoText}>{undoing ? '…' : '↩ Undo'}</Text>
              </Pressable>
            ) : (
              // Reserve space so the button buttons don't shift
              <View style={styles.undoPlaceholder} />
            )}
          </View>
        </View>
      )}

      {/* Match popup */}
      <Modal visible={!!matchPopup} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.matchCard}>
            <Text style={styles.matchEmoji} accessibilityElementsHidden importantForAccessibility="no">🎉</Text>
            <Text style={styles.matchTitle} accessibilityRole="header">It's a Match!</Text>
            <Text style={styles.matchSub}>
              You and {matchPopup?.other_user?.name || 'someone'} liked each other!
            </Text>
            <View style={styles.matchAnimals}>
              <Text style={styles.matchAnimalEmoji}>{animalEmoji(user?.animal)}</Text>
              <Text style={[styles.matchAnimalEmoji, { color: C.gold, fontSize: 22 }]}>❤️</Text>
              <Text style={styles.matchAnimalEmoji}>{animalEmoji(matchPopup?.other_user?.animal)}</Text>
            </View>
            <Pressable
              style={styles.matchBtn}
              onPress={() => setMatchPopup(null)}
              accessibilityRole="button"
              accessibilityLabel="Dismiss and keep swiping"
            >
              <Text style={styles.matchBtnText}>Keep Swiping</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

// ── Card content (shared between active + peek card) ─────────────────────────

function CardContent({ user }: { user: DiscoverUser }) {
  const [imgError, setImgError] = useState(false);
  const resolvedUrl = resolveAvatarUrl(user.avatar_url);

  return (
    <ScrollView style={styles.cardScroll} contentContainerStyle={styles.cardScrollContent} scrollEnabled showsVerticalScrollIndicator={false}>
      {/* Avatar header */}
      <View style={styles.cardHeader}>
        {resolvedUrl && !imgError ? (
          <Image
            source={{ uri: resolvedUrl }}
            style={styles.cardAvatar}
            onError={() => setImgError(true)}
          />
        ) : (
          <View style={styles.cardAvatarFallback}>
            <Text style={styles.cardAvatarEmoji}>{animalEmoji(user.animal)}</Text>
          </View>
        )}

        <Text style={styles.cardName}>{user.name || 'Anonymous'}</Text>
        {user.animal && (
          <Text style={styles.cardAnimal}>{capitalise(user.animal)}</Text>
        )}
        {user.location && (
          <Text style={styles.cardLocation}>📍 {user.location}</Text>
        )}
      </View>

      {/* Body */}
      <View style={styles.cardBody}>
        {user.bio && (
          <Text style={styles.cardBio}>
            {user.bio.length > 200 ? user.bio.slice(0, 200).trimEnd() + '…' : user.bio}
          </Text>
        )}

        {(user.personality_traits?.length ?? 0) > 0 && (
          <View style={styles.traitRow}>
            {user.personality_traits!.map((t, i) => (
              <View key={i} style={styles.traitPill}>
                <Text style={styles.traitText}>{t}</Text>
              </View>
            ))}
          </View>
        )}
      </View>
    </ScrollView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  shell:      { flex: 1, backgroundColor: C.bg },
  header:     { paddingHorizontal: 20, paddingTop: 56, paddingBottom: 12, alignItems: 'center' },
  headerTitle:{ fontSize: 28, fontWeight: '700', color: C.text, letterSpacing: 1 },
  headerSub:  { fontSize: 13, color: C.textSec, marginTop: 2 },

  center:     { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  centerText: { color: C.textSec, marginTop: 14, fontSize: 15 },
  emptyEmoji: { fontSize: 52, marginBottom: 12 },
  emptyTitle: { fontSize: 20, fontWeight: '700', color: C.text, marginBottom: 6 },
  emptySub:   { fontSize: 14, color: C.textSec, textAlign: 'center' },
  refreshBtn: {
    marginTop: 24, backgroundColor: C.accent,
    borderRadius: 10, paddingHorizontal: 28, paddingVertical: 13,
  },
  refreshBtnText: { color: C.text, fontWeight: '600', fontSize: 15 },

  // Card area
  cardArea: { flex: 1, alignItems: 'center', justifyContent: 'flex-start', paddingHorizontal: 16, paddingBottom: 16 },

  card: {
    position: 'absolute',
    width: '100%',
    maxWidth: 420,
    backgroundColor: C.bgCard,
    borderRadius: 20,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOpacity: 0.45,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 10 },
    elevation: 10,
    top: 0,
    bottom: 100, // leave room for buttons
    left: 16,
    right: 16,
  },
  cardBehind: {
    transform: [{ scale: 0.96 }, { translateY: 12 }],
    opacity: 0.7,
    zIndex: 0,
  },

  // Swipe labels
  swipeLabel: {
    position: 'absolute',
    top: 32,
    zIndex: 10,
    borderWidth: 3,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  likeLabel:  { right: 24, borderColor: C.gold, transform: [{ rotate: '12deg' }] },
  passLabel:  { left: 24, borderColor: C.errorLight, transform: [{ rotate: '-12deg' }] },
  likeLabelText: { color: C.gold, fontSize: 22, fontWeight: '800', letterSpacing: 1 },
  passLabelText: { color: C.errorLight, fontSize: 22, fontWeight: '800', letterSpacing: 1 },

  // Card content
  cardScroll: { flex: 1 },
  cardScrollContent: { paddingBottom: 20 },
  cardHeader: {
    backgroundColor: C.bgBrand,
    paddingTop: 36,
    paddingBottom: 24,
    alignItems: 'center',
    paddingHorizontal: 20,
  },
  cardAvatar: { width: 100, height: 100, borderRadius: 50, marginBottom: 14, borderWidth: 3, borderColor: 'rgba(255,255,255,0.2)' },
  cardAvatarFallback: { width: 100, height: 100, borderRadius: 50, backgroundColor: C.bgHover, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  cardAvatarEmoji: { fontSize: 52, lineHeight: 62 },
  cardName:   { fontSize: 26, fontWeight: '600', color: C.text, marginBottom: 4 },
  cardAnimal: { fontSize: 16, color: C.gold, fontStyle: 'italic', marginBottom: 4 },
  cardLocation: { fontSize: 13, color: 'rgba(255,255,255,0.6)', marginTop: 2 },
  cardBody:   { padding: 20 },
  cardBio:    { fontSize: 15, color: C.textSurface, lineHeight: 23, marginBottom: 14 },
  traitRow:   { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  traitPill:  { backgroundColor: C.bgHover, borderRadius: 20, paddingHorizontal: 12, paddingVertical: 5 },
  traitText:  { color: C.textSec, fontSize: 13, fontStyle: 'italic' },

  // Buttons
  buttons: {
    position: 'absolute',
    bottom: 16,
    flexDirection: 'row',
    gap: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btn: {
    width: 64, height: 64, borderRadius: 32,
    alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 8, shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  passBtn:  { backgroundColor: C.bgCard, borderWidth: 2, borderColor: 'rgba(252,129,129,0.4)' },
  likeBtn:  { backgroundColor: '#ed64a6', borderWidth: 0 },
  btnPressed: { opacity: 0.75 },
  btnEmoji: { fontSize: 26, lineHeight: 30 },

  // Error banner
  errorBanner: {
    position: 'absolute',
    bottom: 92,
    left: 16, right: 16,
    backgroundColor: 'rgba(197,48,48,0.2)',
    borderColor: 'rgba(197,48,48,0.4)',
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  errorText: { color: C.errorLight, fontSize: 13, textAlign: 'center' },

  // Match modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.8)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  matchCard: {
    backgroundColor: C.bgCard,
    borderRadius: 24,
    padding: 40,
    width: '100%',
    maxWidth: 360,
    alignItems: 'center',
    shadowColor: '#000', shadowOpacity: 0.6, shadowRadius: 32, shadowOffset: { width: 0, height: 16 },
    elevation: 20,
  },
  matchEmoji: { fontSize: 44, marginBottom: 8 },
  matchTitle: { fontSize: 30, fontWeight: '700', color: C.gold, marginBottom: 8, letterSpacing: 0.5 },
  matchSub:   { fontSize: 15, color: C.textSec, textAlign: 'center', marginBottom: 24 },
  matchAnimals: { flexDirection: 'row', alignItems: 'center', gap: 16, marginBottom: 28 },
  matchAnimalEmoji: { fontSize: 48 },
  matchBtn: {
    backgroundColor: C.gold,
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 40,
  },
  matchBtnText: { color: '#0D0B1A', fontSize: 16, fontWeight: '700' },

  // Undo
  undoRow:         { position: 'absolute', bottom: -4, alignItems: 'center', width: '100%' },
  undoBtn:         { paddingVertical: 8, paddingHorizontal: 20 },
  undoText:        { color: C.textSec, fontSize: 13, fontWeight: '500', textDecorationLine: 'underline' },
  undoPlaceholder: { height: 32 },
});
