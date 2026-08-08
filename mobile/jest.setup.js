// expo-secure-store touches native keychain APIs that do not exist under Jest,
// so token storage is backed by an in-memory map for tests.
jest.mock('expo-secure-store', () => {
  const store = new Map();
  return {
    getItemAsync: jest.fn(async (k) => (store.has(k) ? store.get(k) : null)),
    setItemAsync: jest.fn(async (k, v) => { store.set(k, v); }),
    deleteItemAsync: jest.fn(async (k) => { store.delete(k); }),
    __store: store,
  };
});

// `api()` logs failures under __DEV__, and several tests deliberately provoke
// failures (offline, timeout, bad payload). Those warnings are the expected
// output of a passing test, so they are swallowed rather than printed — 30 lines
// of stack trace per test makes a green run look broken.
const realWarn = console.warn;
beforeAll(() => {
  console.warn = (...args) => {
    const msg = String(args[0] ?? '');
    if (msg.startsWith('[api]') || msg.includes('useNativeDriver') || msg.includes('Animated:')) {
      return;
    }
    realWarn(...args);
  };
});
afterAll(() => {
  console.warn = realWarn;
});
