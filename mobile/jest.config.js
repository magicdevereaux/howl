/**
 * jest-expo is the preset that matches this SDK (53) — it wires the Metro
 * transformer, the React Native module mocks and the `expo-*` shims that a plain
 * jest install cannot resolve.
 *
 * Scope note: these tests cover pure logic and module *contracts*, not rendered
 * screens. Rendering the app's screens needs expo-router's context plus a
 * navigation tree, which is a bigger lift than GAPS #29 asks for — see the
 * follow-up note in docs/GAPS.md.
 */
module.exports = {
  preset: 'jest-expo',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  testMatch: ['**/*.test.ts', '**/*.test.tsx'],
  testPathIgnorePatterns: ['/node_modules/', '/.expo/'],
  clearMocks: true,
  restoreMocks: true,
  collectCoverageFrom: ['src/**/*.{ts,tsx}', '!src/**/*.d.ts'],
};
