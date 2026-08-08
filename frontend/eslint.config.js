import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import prettier from 'eslint-config-prettier';

/**
 * Flat config (ESLint 9). Deliberately not run as an autofix pass over existing
 * source — see docs/GAPS.md #29. The point is to have the rules in place and
 * reporting; cleaning up what they find is separate work.
 *
 * `react/prop-types` is off because this codebase uses heavy prop drilling with
 * no PropTypes anywhere (ProfileView alone takes 24 props). Turning it on would
 * produce hundreds of findings that say nothing about correctness. The real fix
 * is GAPS #33 — decomposing App.jsx — not annotating the current shape.
 */
export default [
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**'] },

  js.configs.recommended,

  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2021 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off', // Vite's JSX transform handles this.
      'react/prop-types': 'off',
      // Off, not warn: a literal ' or " in JSX text renders correctly. The rule
      // guards against an old ambiguity that modern JSX does not have, and it
      // fired 20 times on ordinary English copy ("You've", "It's"). Escaping all
      // of it would make the source harder to read to satisfy a cosmetic rule.
      'react/no-unescaped-entities': 'off',
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },

  {
    // Vitest injects describe/it/expect as globals (globals: true).
    files: ['**/*.{test,spec}.{js,jsx}', 'vitest.setup.js'],
    languageOptions: { globals: { ...globals.node, ...globals.vitest } },
  },

  { files: ['vite.config.js', 'vitest.config.js'], languageOptions: { globals: globals.node } },

  prettier, // must stay last so it can switch off stylistic rules
];
