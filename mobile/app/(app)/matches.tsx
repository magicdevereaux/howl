import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { api } from '../../src/api/client';
import { useAuth } from '../../src/auth/AuthContext';
import { useUnread } from '../../src/contexts/UnreadContext';
import { colors as C } from '../../src/theme';
import { animalEmoji, capitalise, resolveAvatarUrl } from '../../src/utils/avatar';

interface OtherUser {
  id: number;
  name: string | null;
  animal: string | null;
  avatar_url: string | null;
}

interface LastMessage {
  sender_id: number;
  content: string | null;
  created_at: string;
}

interface Match {
  id: number;
  matched_at: string;
  other_user: OtherUser;
  unread_count: number;
  last_message: LastMessage | null;
}

export default function MatchesScreen() {
  const { user }           = useAuth();
  const { setTotalUnread } = useUnread();

  const [matches,  setMatches]  = useState<Match[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  const fetchMatches = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    const res = await api<Match[]>('/api/users/matches');
    if (!silent) setLoading(false);
    if (res.ok) {
      setMatches(res.data);
      // Keep the tab badge in sync
      setTotalUnread(res.data.reduce((sum, m) => sum + m.unread_count, 0));
    } else {
      setError(res.error);
    }
  }, [setTotalUnread]);

  // Refetch whenever this tab comes into focus (e.g. returning from chat)
  useFocusEffect(
    useCallback(() => {
      fetchMatches(matches.length > 0); // silent if we already have data
    }, [fetchMatches]),
  );

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchMatches(true);
    setRefreshing(false);
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={C.accentHover} size="large" />
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Text
          style={styles.errorText}
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
        >⚠️ {error}</Text>
        <Pressable
          style={styles.retryBtn}
          onPress={() => fetchMatches()}
          accessibilityRole="button"
          accessibilityLabel="Retry loading your matches"
        >
          <Text style={styles.retryBtnText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.shell}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Matches</Text>
        <Text style={styles.headerSub}>Spirit animals that connected with yours</Text>
      </View>

      {matches.length === 0 ? (
        <FlatList
          data={[]}
          renderItem={null}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.accentHover} />}
          ListEmptyComponent={(
            <View style={styles.empty}>
              <Text
                style={styles.emptyEmoji}
                accessibilityElementsHidden
                importantForAccessibility="no"
              >❤️</Text>
              <Text style={styles.emptyTitle} accessibilityRole="header">No matches yet</Text>
              <Text style={styles.emptySub}>Go discover some spirit animals!</Text>
            </View>
          )}
        />
      ) : (
        <FlatList
          data={matches}
          keyExtractor={(m) => String(m.id)}
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.accentHover} />}
          renderItem={({ item: m }) => (
            <MatchRow match={m} myId={user?.id ?? 0} />
          )}
        />
      )}
    </View>
  );
}

function MatchRow({ match: m, myId }: { match: Match; myId: number }) {
  const [imgError, setImgError] = useState(false);
  const resolvedUrl = resolveAvatarUrl(m.other_user.avatar_url);
  const hasUnread   = m.unread_count > 0;

  const openChat = () => {
    router.push({
      pathname: '/(app)/chat/[matchId]',
      params: {
        matchId:     m.id,
        name:        m.other_user.name    ?? '',
        animal:      m.other_user.animal  ?? '',
        otherUserId: m.other_user.id,
      },
    });
  };

  return (
    <Pressable
      style={({ pressed }) => [rowStyles.row, hasUnread && rowStyles.rowUnread, pressed && rowStyles.rowPressed]}
      onPress={openChat}
      accessibilityRole="button"
      accessible
      accessibilityLabel={[
        `Chat with ${m.other_user.name || 'Anonymous'}`,
        m.other_user.animal ? capitalise(m.other_user.animal) : null,
        hasUnread
          ? `${m.unread_count} unread ${m.unread_count === 1 ? 'message' : 'messages'}`
          : null,
        m.last_message
          ? `Last message: ${m.last_message.sender_id === myId ? 'you said ' : ''}${m.last_message.content ?? 'message deleted'}`
          : 'No messages yet',
      ].filter(Boolean).join('. ')}
      accessibilityHint="Opens the conversation"
    >
      {/* Avatar */}
      <View style={rowStyles.avatarWrap}>
        {resolvedUrl && !imgError ? (
          <Image source={{ uri: resolvedUrl }} style={rowStyles.avatar} onError={() => setImgError(true)} />
        ) : (
          <View style={rowStyles.avatarFallback}>
            <Text style={rowStyles.avatarEmoji}>{animalEmoji(m.other_user.animal)}</Text>
          </View>
        )}
        {hasUnread && (
          <View style={rowStyles.badge}>
            <Text style={rowStyles.badgeText}>{m.unread_count > 9 ? '9+' : String(m.unread_count)}</Text>
          </View>
        )}
      </View>

      {/* Text */}
      <View style={rowStyles.body}>
        <View style={rowStyles.nameRow}>
          <Text style={rowStyles.name}>{m.other_user.name || 'Anonymous'}</Text>
          {m.other_user.animal && <Text style={rowStyles.animal}>{capitalise(m.other_user.animal)}</Text>}
        </View>
        {m.last_message ? (
          <Text style={rowStyles.preview} numberOfLines={1}>
            {m.last_message.sender_id === myId ? 'You: ' : ''}
            {m.last_message.content ?? 'Message deleted'}
          </Text>
        ) : (
          <Text style={rowStyles.newMatch}>Matched {new Date(m.matched_at).toLocaleDateString()}</Text>
        )}
      </View>

      <Text
        style={rowStyles.chevron}
        accessibilityElementsHidden
        importantForAccessibility="no"
      >›</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  shell:      { flex: 1, backgroundColor: C.bg },
  header:     { paddingHorizontal: 20, paddingTop: 56, paddingBottom: 16, alignItems: 'center' },
  headerTitle:{ fontSize: 24, fontWeight: '700', color: C.text },
  headerSub:  { fontSize: 13, color: C.textSec, marginTop: 4 },
  list:       { paddingHorizontal: 16, paddingBottom: 24 },
  center:     { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  empty:      { alignItems: 'center', paddingTop: 80 },
  emptyEmoji: { fontSize: 48, marginBottom: 12 },
  emptyTitle: { fontSize: 20, fontWeight: '700', color: C.text, marginBottom: 6 },
  emptySub:   { fontSize: 14, color: C.textSec, textAlign: 'center' },
  errorText:  { color: C.errorLight, fontSize: 14, marginBottom: 16, textAlign: 'center' },
  retryBtn:   { backgroundColor: C.accent, borderRadius: 10, paddingHorizontal: 24, paddingVertical: 11 },
  retryBtnText: { color: C.text, fontWeight: '600', fontSize: 14 },
});

const rowStyles = StyleSheet.create({
  row: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: C.bgCard, borderRadius: 14,
    padding: 14, marginBottom: 10, gap: 12,
  },
  rowUnread:  { borderLeftWidth: 3, borderLeftColor: C.gold },
  rowPressed: { opacity: 0.75 },
  avatarWrap: { position: 'relative' },
  avatar:     { width: 54, height: 54, borderRadius: 27 },
  avatarFallback: {
    width: 54, height: 54, borderRadius: 27,
    backgroundColor: C.bgHover, alignItems: 'center', justifyContent: 'center',
  },
  avatarEmoji:  { fontSize: 28, lineHeight: 34 },
  badge: {
    position: 'absolute', top: -4, right: -4,
    backgroundColor: C.gold, borderRadius: 10,
    minWidth: 18, height: 18,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4,
  },
  badgeText: { color: '#0D0B1A', fontSize: 10, fontWeight: '700' },
  body:     { flex: 1, minWidth: 0 },
  nameRow:  { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginBottom: 3 },
  name:     { fontSize: 16, fontWeight: '600', color: C.text },
  animal:   { fontSize: 13, color: C.gold, fontStyle: 'italic' },
  preview:  { fontSize: 13, color: C.textSec },
  newMatch: { fontSize: 12, color: C.textDisabled, fontStyle: 'italic' },
  chevron:  { color: C.textDisabled, fontSize: 22, fontWeight: '300' },
});
