// This will be replaced at build time with a boolean value
declare const __DEV_WATCH__: boolean;

// Create a logger for a specific namespace
export const createLogger = (namespace: string) => {
  // Logger functions that only activate in dev-watch mode
  const logger = {
    debug: (message: string, ...args: any[]) => {
      if (__DEV_WATCH__) console.debug(`[${namespace}] ${message}`, ...args);
    },

    info: (message: string, ...args: any[]) => {
      if (__DEV_WATCH__) console.info(`[${namespace}] ${message}`, ...args);
    },

    warn: (message: string, ...args: any[]) => {
      if (__DEV_WATCH__) console.warn(`[${namespace}] ${message}`, ...args);
    },

    // Always log errors, even in production
    error: (message: string, ...args: any[]) => {
      console.error(`[${namespace}] ${message}`, ...args);
    },

    // Lazy evaluation for expensive logs
    debugIf: (fn: () => string) => {
      if (__DEV_WATCH__) console.debug(`[${namespace}] ${fn()}`);
    },
  };

  return logger;
};
