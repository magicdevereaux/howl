import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { api } from '../../../src/api/client';
import { useMatchWebSocket, WsMessage } from '../../../src/hooks/useMatchWebSocket';
import { colors as C } from '../../../src/theme';
import { animalEmoji, capitalise } from '../../../src/utils/avatar';

// ── Types ─────────────────────────────────────────────────────────────────────

type ChatMessage = WsMessage;

interface PageResponse {
  messages: ChatMessage[];
  has_more: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ── Screen ────────────────────────────────────────────────────────────────────

export default function ChatScreen() {
  const { matchId, name, animal, otherUserId } = useLocalSearchParams<{
    matchId: string;
    name: string;
    animal: string;
    otherUserId: string;
  }>();

  const mid = Number(matchId);

  // ── State ─────────────────────────────────────────────────────────────────

  // Messages stored oldest-first; FlatList uses inverted with reversed data
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingInitial, setLoadingInitial] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [typingUser, setTypingUser] = useState<string | null>(null);

  const typingHideRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendTypingRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef         = useRef<TextInput>(null);
  const seenIdsRef       = useRef(new Set<number>()); // dedup between REST + WS

  // ── Block / report menu ───────────────────────────────────────────────────
  const [menuOpen,       setMenuOpen]       = useState(false);
  const [reportOpen,     setReportOpen]     = useState(false);
  const [reportReason,   setReportReason]   = useState('');
  const [reportLoading,  setReportLoading]  = useState(false);
  const [blockLoading,   setBlockLoading]   = useState(false);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  const REPORT_REASONS = [
    { value: 'spam_scam',             label: 'Spam or scam' },
    { value: 'inappropriate_content', label: 'Inappropriate content' },
    { value: 'harassment',            label: 'Harassment or abuse' },
    { value: 'fake_profile',          label: 'Fake or impersonating profile' },
    { value: 'underage_user',         label: 'Underage user' },
    { value: 'other',                 label: 'Other' },
  ];

  const handleReport = async () => {
    if (!reportReason) return;
    setReportLoading(true);
    await api('/api/reports', {
      method: 'POST',
      body: JSON.stringify({ reported_user_id: Number(otherUserId), reason: reportReason }),
    });
    setReportLoading(false);
    setReportOpen(false);
    setReportReason('');
    setActionFeedback('Report submitted. Thank you.');
    setTimeout(() => setActionFeedback(null), 3000);
  };

  const handleBlock = async () => {
    setBlockLoading(true);
    const res = await api('/api/blocks', {
      method: 'POST',
      body: JSON.stringify({ blocked_id: Number(otherUserId) }),
    });
    setBlockLoading(false);
    setMenuOpen(false);
    if (res.ok) router.back();
  };

  // ── Data loading ──────────────────────────────────────────────────────────

  const loadMessages = useCallback(async (beforeId?: number) => {
    const path = `/api/matches/${mid}/messages` + (beforeId ? `?before_id=${beforeId}` : '');
    const res = await api<PageResponse>(path);
    if (!res.ok) return;

    const fresh = res.data.messages.filter((m) => {
      if (seenIdsRef.current.has(m.id)) return false;
      seenIdsRef.current.add(m.id);
      return true;
    });

    setMessages((prev) =>
      beforeId
        ? [...fresh, ...prev]   // prepend older messages
        : fresh,                // initial load
    );
    setHasMore(res.data.has_more);
  }, [mid]);

  useEffect(() => {
    (async () => {
      await loadMessages();
      setLoadingInitial(false);
    })();
  }, [loadMessages]);

  const loadOlder = async () => {
    if (loadingMore || !hasMore || messages.length === 0) return;
    setLoadingMore(true);
    await loadMessages(messages[0].id);
    setLoadingMore(false);
  };

  // ── WebSocket events ──────────────────────────────────────────────────────

  const handleWsEvent = useCallback((event: Parameters<typeof useMatchWebSocket>[1] extends (e: infer E) => void ? E : never) => {
    if (event.type === 'new_message' || event.type === 'message_deleted') {
      const msg = event.message;
      if (seenIdsRef.current.has(msg.id)) {
        // Message already known — update it (e.g. deletion or read receipt)
        setMessages((prev) => prev.map((m) => m.id === msg.id ? msg : m));
      } else {
        seenIdsRef.current.add(msg.id);
        setMessages((prev) => [...prev, msg]);
      }
    } else if (event.type === 'typing') {
      setTypingUser(event.user_name ?? null);
      if (typingHideRef.current) clearTimeout(typingHideRef.current);
      typingHideRef.current = setTimeout(() => setTypingUser(null), 3000);
    }
  }, []);

  const { sendTyping } = useMatchWebSocket(mid, handleWsEvent);

  // ── Sending ───────────────────────────────────────────────────────────────

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setSendError(null);
    setInput('');

    const res = await api<ChatMessage>(
      `/api/matches/${mid}/messages`,
      { method: 'POST', body: JSON.stringify({ content: text }) },
    );
    setSending(false);

    if (!res.ok) {
      setSendError(res.error);
      setInput(text); // restore
      return;
    }

    // WS echo will arrive and add it via seenIds dedup; also add directly
    // in case WS is momentarily disconnected
    const msg = res.data;
    if (!seenIdsRef.current.has(msg.id)) {
      seenIdsRef.current.add(msg.id);
      setMessages((prev) => [...prev, msg]);
    }
  };

  const handleInputChange = (text: string) => {
    setInput(text);
    if (sendTypingRef.current) clearTimeout(sendTypingRef.current);
    sendTypingRef.current = setTimeout(sendTyping, 500);
  };

  // ── Cleanup ───────────────────────────────────────────────────────────────

  useEffect(() => () => {
    if (typingHideRef.current) clearTimeout(typingHideRef.current);
    if (sendTypingRef.current)  clearTimeout(sendTypingRef.current);
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────

  // FlatList data: newest-first for inverted list (newest appears at bottom)
  const listData = [...messages].reverse();

  return (
    <SafeAreaView style={styles.shell}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable
          style={styles.backBtn}
          onPress={() => router.back()}
          accessibilityRole="button"
          accessibilityLabel="Back to matches"
        >
          <Text style={styles.backText}>← Matches</Text>
        </Pressable>
        <View style={styles.headerCenter}>
          <Text style={styles.headerName} accessibilityRole="header">{name || 'Chat'}</Text>
          {animal ? (
            <Text style={styles.headerAnimal}>{animalEmoji(animal)} {capitalise(animal)}</Text>
          ) : null}
        </View>
        <Pressable
          style={styles.headerRight}
          onPress={() => setMenuOpen(true)}
          accessibilityRole="button"
          accessibilityLabel={`More options for ${name || 'this conversation'}`}
          accessibilityHint="Report or block this person"
        >
          {/* Decorative glyph; the label above carries the meaning. */}
          <Text style={styles.menuDots} accessibilityElementsHidden importantForAccessibility="no">⋯</Text>
        </Pressable>
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 24}
      >
        {/* Message list */}
        {loadingInitial ? (
          <View style={styles.center}>
            <ActivityIndicator color={C.accentHover} size="large" />
          </View>
        ) : (
          <FlatList
            data={listData}
            keyExtractor={(m) => String(m.id)}
            inverted
            contentContainerStyle={styles.listContent}
            // Load older messages when user scrolls to the "top" (which is
            // the end of an inverted list)
            onEndReached={loadOlder}
            onEndReachedThreshold={0.3}
            ListFooterComponent={
              loadingMore
                ? <ActivityIndicator color={C.accentHover} style={{ paddingVertical: 12 }} />
                : null
            }
            renderItem={({ item }) => <Bubble msg={item} />}
          />
        )}

        {/* Typing indicator */}
        {typingUser && (
          <View style={styles.typingRow}>
            <Text style={styles.typingText}>{typingUser} is typing…</Text>
          </View>
        )}

        {/* Send error */}
        {sendError && (
          <View style={styles.sendErrorRow}>
            <Text style={styles.sendErrorText}>⚠️ {sendError}</Text>
          </View>
        )}

        {/* Input bar */}
        <View style={styles.inputBar}>
          <TextInput
            ref={inputRef}
            style={styles.input}
            value={input}
            onChangeText={handleInputChange}
            placeholder={`Message ${name || 'them'}…`}
            placeholderTextColor={C.textDisabled}
            multiline
            maxLength={2000}
            returnKeyType="send"
            blurOnSubmit={false}
            onSubmitEditing={handleSend}
          />
          <Pressable
            style={[styles.sendBtn, (!input.trim() || sending) && styles.sendBtnDisabled]}
            onPress={handleSend}
            disabled={!input.trim() || sending}
            accessibilityRole="button"
            accessibilityLabel={sending ? 'Sending message' : 'Send message'}
            accessibilityState={{ disabled: !input.trim() || sending, busy: sending }}
          >
            {sending
              ? <ActivityIndicator color={C.text} size="small" />
              : <Text style={styles.sendIcon} accessibilityElementsHidden importantForAccessibility="no">➤</Text>
            }
          </Pressable>
        </View>
      </KeyboardAvoidingView>
      {/* Action feedback toast */}
      {actionFeedback && (
        <View
          style={styles.toast}
          pointerEvents="none"
          accessibilityRole="alert"
          accessibilityLiveRegion="polite"
        >
          <Text style={styles.toastText}>{actionFeedback}</Text>
        </View>
      )}

      {/* ⋯ menu modal */}
      <Modal visible={menuOpen} transparent animationType="fade" onRequestClose={() => setMenuOpen(false)}>
        <Pressable style={styles.menuOverlay} onPress={() => setMenuOpen(false)}>
          <View style={styles.menuSheet}>
            <Text style={styles.menuTitle}>{name || 'Options'}</Text>

            <Pressable
              style={styles.menuItem}
              onPress={() => { setMenuOpen(false); setReportOpen(true); }}
              accessibilityRole="button"
              accessibilityLabel={`Report ${name || 'this person'}`}
            >
              <Text style={styles.menuItemText}>🚩  Report</Text>
            </Pressable>

            <View style={styles.menuDivider} />

            <Pressable
              style={[styles.menuItem, blockLoading && styles.menuItemDisabled]}
              onPress={handleBlock}
              disabled={blockLoading}
              accessibilityRole="button"
              accessibilityLabel={`Block ${name || 'this person'}`}
              accessibilityHint="Removes the match and hides you from each other"
              accessibilityState={{ disabled: blockLoading, busy: blockLoading }}
            >
              <Text style={[styles.menuItemText, styles.menuItemDanger]}>
                {blockLoading ? 'Blocking…' : '🚫  Block'}
              </Text>
            </Pressable>

            <View style={styles.menuDivider} />

            <Pressable
              style={styles.menuItem}
              onPress={() => setMenuOpen(false)}
              accessibilityRole="button"
              accessibilityLabel="Cancel"
            >
              <Text style={[styles.menuItemText, { textAlign: 'center', color: C.textSec }]}>Cancel</Text>
            </Pressable>
          </View>
        </Pressable>
      </Modal>

      {/* Report reason modal */}
      <Modal visible={reportOpen} transparent animationType="slide" onRequestClose={() => setReportOpen(false)}>
        <View style={styles.reportOverlay}>
          <View style={styles.reportSheet}>
            <Text style={styles.reportTitle}>Report {name || 'this user'}</Text>
            <Text style={styles.reportSub}>Reports are reviewed by our team.</Text>

            {REPORT_REASONS.map((r) => (
              <Pressable
                key={r.value}
                style={[styles.reasonRow, reportReason === r.value && styles.reasonRowSelected]}
                onPress={() => setReportReason(r.value)}
              >
                <View style={[styles.reasonRadio, reportReason === r.value && styles.reasonRadioSelected]} />
                <Text style={styles.reasonLabel}>{r.label}</Text>
              </Pressable>
            ))}

            <View style={styles.reportActions}>
              <Pressable
                style={styles.reportCancelBtn}
                onPress={() => { setReportOpen(false); setReportReason(''); }}
              >
                <Text style={styles.reportCancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.reportSubmitBtn, (!reportReason || reportLoading) && styles.reportSubmitDisabled]}
                onPress={handleReport}
                disabled={!reportReason || reportLoading}
              >
                <Text style={styles.reportSubmitText}>
                  {reportLoading ? 'Submitting…' : 'Submit'}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

    </SafeAreaView>
  );
}

// ── Message bubble ─────────────────────────────────────────────────────────────

function Bubble({ msg }: { msg: ChatMessage }) {
  if (msg.deleted_at) {
    return (
      <View style={[bubbleStyles.wrap, msg.is_mine && bubbleStyles.wrapMine]}>
        <View style={[bubbleStyles.deleted, msg.is_mine && bubbleStyles.deletedMine]}>
          <Text style={bubbleStyles.deletedText}>🗑 Message deleted</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={[bubbleStyles.wrap, msg.is_mine && bubbleStyles.wrapMine]}>
      <View style={[bubbleStyles.bubble, msg.is_mine ? bubbleStyles.bubbleMine : bubbleStyles.bubbleTheirs]}>
        <Text style={[bubbleStyles.text, msg.is_mine && bubbleStyles.textMine]}>
          {msg.content}
        </Text>
        <Text style={[bubbleStyles.meta, msg.is_mine && bubbleStyles.metaMine]}>
          {formatTime(msg.created_at)}
          {msg.is_mine && (
            <Text style={{ color: msg.read_at ? C.accentHover : C.textDisabled }}>
              {msg.read_at ? '  ✓✓' : '  ✓'}
            </Text>
          )}
        </Text>
      </View>
    </View>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  shell:      { flex: 1, backgroundColor: C.bg },
  flex:       { flex: 1 },
  center:     { flex: 1, alignItems: 'center', justifyContent: 'center' },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.35)',
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  backBtn:     { padding: 4, minWidth: 80 },
  backText:    { color: C.accentHover, fontSize: 14, fontWeight: '500' },
  headerCenter:{ flex: 1, alignItems: 'center' },
  headerName:  { color: C.text, fontSize: 16, fontWeight: '700' },
  headerAnimal:{ color: C.gold, fontSize: 12, fontStyle: 'italic', marginTop: 1 },
  headerRight: { minWidth: 80 },

  listContent: { paddingHorizontal: 12, paddingVertical: 12 },

  typingRow:   { paddingHorizontal: 16, paddingBottom: 4 },
  typingText:  { color: C.textSec, fontSize: 13, fontStyle: 'italic' },

  sendErrorRow: {
    backgroundColor: 'rgba(197,48,48,0.15)',
    borderTopWidth: 1,
    borderTopColor: 'rgba(197,48,48,0.3)',
    padding: 10,
  },
  sendErrorText: { color: C.errorLight, fontSize: 13, textAlign: 'center' },

  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: C.bgCard,
    borderTopWidth: 1,
    borderTopColor: C.border,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 10,
  },
  input: {
    flex: 1,
    backgroundColor: C.bgInput,
    borderWidth: 1.5,
    borderColor: C.border,
    borderRadius: 22,
    color: C.text,
    fontSize: 15,
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 10 : 8,
    paddingBottom: Platform.OS === 'ios' ? 10 : 8,
    maxHeight: 120,
  },
  sendBtn: {
    width: 42, height: 42, borderRadius: 21,
    backgroundColor: C.accent,
    alignItems: 'center', justifyContent: 'center',
  },
  sendBtnDisabled: { backgroundColor: C.bgHover },
  sendIcon: { color: C.text, fontSize: 18, marginLeft: 2 },

  // Header menu button
  menuDots: { color: C.textSec, fontSize: 22, fontWeight: '600', textAlign: 'right' },

  // Feedback toast
  toast: {
    position: 'absolute', bottom: 90, left: 24, right: 24,
    backgroundColor: 'rgba(107,63,160,0.9)', borderRadius: 10,
    padding: 12, alignItems: 'center',
  },
  toastText: { color: C.text, fontSize: 13, fontWeight: '500' },

  // ⋯ menu
  menuOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  menuSheet: {
    backgroundColor: C.bgCard, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingTop: 20, paddingBottom: 36, paddingHorizontal: 0,
  },
  menuTitle:  { color: C.textSec, fontSize: 13, textAlign: 'center', paddingBottom: 16, paddingHorizontal: 20 },
  menuItem:   { paddingVertical: 16, paddingHorizontal: 24 },
  menuItemDisabled: { opacity: 0.5 },
  menuItemText:   { color: C.text, fontSize: 16 },
  menuItemDanger: { color: C.errorLight },
  menuDivider: { height: 1, backgroundColor: C.border, marginHorizontal: 16 },

  // Report sheet
  reportOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  reportSheet: {
    backgroundColor: C.bgCard, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 24, paddingBottom: 40,
  },
  reportTitle: { color: C.text, fontSize: 18, fontWeight: '700', marginBottom: 6 },
  reportSub:   { color: C.textSec, fontSize: 13, marginBottom: 20 },
  reasonRow: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    paddingVertical: 12, paddingHorizontal: 4,
    borderBottomWidth: 1, borderBottomColor: C.borderSubtle,
  },
  reasonRowSelected: { borderBottomColor: C.accent },
  reasonRadio: {
    width: 18, height: 18, borderRadius: 9,
    borderWidth: 2, borderColor: C.textDisabled,
  },
  reasonRadioSelected: { borderColor: C.accentHover, backgroundColor: C.accentHover },
  reasonLabel: { color: C.textSurface, fontSize: 15 },
  reportActions: { flexDirection: 'row', gap: 12, marginTop: 24 },
  reportCancelBtn: {
    flex: 1, padding: 13, backgroundColor: C.bgHover,
    borderRadius: 10, borderWidth: 1, borderColor: C.border, alignItems: 'center',
  },
  reportCancelText: { color: C.textSec, fontWeight: '600', fontSize: 14 },
  reportSubmitBtn:  { flex: 1, padding: 13, backgroundColor: C.error, borderRadius: 10, alignItems: 'center' },
  reportSubmitDisabled: { backgroundColor: C.bgHover },
  reportSubmitText: { color: C.text, fontWeight: '700', fontSize: 14 },
});

const bubbleStyles = StyleSheet.create({
  wrap:     { marginBottom: 6, flexDirection: 'row' },
  wrapMine: { justifyContent: 'flex-end' },

  bubble: {
    maxWidth: '75%',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  bubbleMine:   { backgroundColor: C.accent, borderBottomRightRadius: 4 },
  bubbleTheirs: { backgroundColor: 'rgba(255,255,255,0.1)', borderBottomLeftRadius: 4 },

  text:     { fontSize: 15, color: C.textSurface, lineHeight: 21 },
  textMine: { color: C.text },

  meta:     { fontSize: 10, color: C.textDisabled, textAlign: 'right', marginTop: 3 },
  metaMine: { color: 'rgba(255,255,255,0.55)' },

  deleted:     { maxWidth: '75%', paddingHorizontal: 12, paddingVertical: 8, borderRadius: 16, borderWidth: 1, borderColor: C.border, borderStyle: 'dashed' },
  deletedMine: { alignSelf: 'flex-end' },
  deletedText: { color: C.textDisabled, fontSize: 13, fontStyle: 'italic' },
});
