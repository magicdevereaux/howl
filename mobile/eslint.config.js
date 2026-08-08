import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

/**
 * Flat config (ESLint 9) for the Expo client.
 *
 * Type-aware linting (`recommendedTypeChecked`) is deliberately NOT enabled: it
 * needs a full program per run and duplicates what `npm run typecheck` already
 * does in CI with `tsc --noEmit`, which is the authority here.
 *
 * As with the web client, this is not run as an autofix pass over existing
 * source — see docs/GAPS.md #29. The deliverable is the rules being in place.
 */
export default [
  { ignores: ['node_modules/**', '.expo/**', 'android/**', 'ios/**', 'dist/**'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.es2021, __DEV__: 'readonly' },
    },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off',   // Expo's JSX transform handles this.
      'react/prop-types': 'off',           // TypeScript covers prop shapes.
      // Off for the same reason as the web client: a literal apostrophe in JSX
      // text renders correctly, and escaping ordinary English copy to satisfy a
      // cosmetic rule makes the source worse.
      'react/no-unescaped-entities': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // Warn, not error: both fire on pre-existing code that this pass is not
      // rewriting (docs/GAPS.md #29 says configure the linters, do not autofix
      // the source). They are reported so they get fixed deliberately, but they
      // do not turn CI red on day one. Current hits are listed in GAPS #29.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-empty-object-type': 'warn',
    },
  },

  {
    // CommonJS config files: `module`, `require`, `process` are node globals.
    files: ['*.config.js', 'babel.config.js', 'metro.config.js', 'jest.setup.js'],
    languageOptions: { sourceType: 'commonjs', globals: globals.node },
  },

  {
    files: ['**/*.test.{ts,tsx}', 'jest.setup.js', 'jest.config.js'],
    languageOptions: { globals: { ...globals.node, ...globals.jest } },
    rules: { '@typescript-eslint/no-explicit-any': 'off' },
  },

  prettier, // last, so it can switch off stylistic rules
];
