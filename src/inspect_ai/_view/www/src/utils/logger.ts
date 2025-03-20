// This will be replaced at build time with a boolean value
declare const __DEV_WATCH__: boolean;
declare const __LOGGING_FILTER__: string;

const getEnabledNamespaces = () => {
  // Split by comma and filter out empty strings
  return __LOGGING_FILTER__
    .split(",")
    .map((ns) => ns.trim())
    .filter(Boolean);
};

const ENABLED_NAMESPACES = new Set<string>(getEnabledNamespaces());
const filterNameSpace = (namespace: string) => {
  if (ENABLED_NAMESPACES.has("*")) return true;

  return ENABLED_NAMESPACES.has(namespace);
};

// Create a logger for a specific namespace
export const createLogger = (namespace: string) => {
  // Logger functions that only activate in dev-watch mode
  const logger = {
    debug: (message: string, ...args: any[]) => {
      if (__DEV_WATCH__ && filterNameSpace(namespace))
        console.debug(`[${namespace}] ${message}`, ...args);
    },

    info: (message: string, ...args: any[]) => {
      if (__DEV_WATCH__ && filterNameSpace(namespace))
        console.info(`[${namespace}] ${message}`, ...args);
    },

    warn: (message: string, ...args: any[]) => {
      if (__DEV_WATCH__ && filterNameSpace(namespace))
        console.warn(`[${namespace}] ${message}`, ...args);
    },

    // Always log errors, even in production
    error: (message: string, ...args: any[]) => {
      console.error(`[${namespace}] ${message}`, ...args);
    },

    // Lazy evaluation for expensive logs
    debugIf: (fn: () => string) => {
      if (__DEV_WATCH__ && filterNameSpace(namespace))
        console.debug(`[${namespace}] ${fn()}`);
    },
  };

  return logger;
};
