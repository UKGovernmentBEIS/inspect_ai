import "@testing-library/jest-dom";

// Setup fake IndexedDB for database tests
import "fake-indexeddb/auto";

// Mock build-time constants used by logger
global.__LOGGING_FILTER__ = "";
global.__DEV_WATCH__ = false;

// Polyfill structuredClone for Node.js versions that don't have it
if (typeof global.structuredClone === "undefined") {
  global.structuredClone = (obj) => {
    return JSON.parse(JSON.stringify(obj));
  };
}
