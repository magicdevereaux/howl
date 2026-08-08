// Adds the jest-dom matchers (toBeInTheDocument, toBeDisabled, …) to expect().
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// RTL does not auto-cleanup unless the test globals are detected at import time;
// being explicit is cheaper than debugging leaked DOM between files.
afterEach(() => {
  cleanup();
});
