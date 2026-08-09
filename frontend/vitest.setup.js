// Adds the jest-dom matchers (toBeInTheDocument, toBeDisabled, …) to expect().
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// jsdom implements no layout, so scrollIntoView does not exist. The chat scrolls
// to the newest message on every render, so without this every chat test throws
// a TypeError that has nothing to do with what is under test.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

// RTL does not auto-cleanup unless the test globals are detected at import time;
// being explicit is cheaper than debugging leaked DOM between files.
afterEach(() => {
  cleanup();
});
