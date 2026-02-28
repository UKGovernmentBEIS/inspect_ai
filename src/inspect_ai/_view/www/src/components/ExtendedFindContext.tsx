import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useRef,
} from "react";

// The search context provides global search assistance. We generally use the
// browser to perform searches using 'find', but this allows for virtual lists
// and other virtualized components to register themselves to be notified when a
// search is requested and no matches are found. In this case, they can 'look ahead'
// and scroll an item into view if it is likely/certain to contain the search term.

// Count total matches across all data items
export type ExtendedCountFn = (term: string) => number;

// Given a search term and a 1-based absolute match index,
// scroll to and highlight that match in the DOM.
export type GoToMatchFn = (
  term: string,
  absoluteIndex: number,
) => Promise<boolean>;

// The context provides an extended search function and a way for the active
// virtual lists to register themselves.
interface ExtendedFindContextType {
  countAllMatches: (term: string) => number;
  registerMatchCounter: (id: string, countFn: ExtendedCountFn) => () => void;
  goToMatch: (term: string, absoluteIndex: number) => Promise<boolean>;
  registerGoToMatch: (id: string, fn: GoToMatchFn) => () => void;
}

const ExtendedFindContext = createContext<ExtendedFindContextType | null>(null);

interface ExtendedFindProviderProps {
  children: ReactNode;
}

export const ExtendedFindProvider = ({
  children,
}: ExtendedFindProviderProps) => {
  const matchCounters = useRef<Map<string, ExtendedCountFn>>(new Map());
  const goToMatchFns = useRef<Map<string, GoToMatchFn>>(new Map());

  const countAllMatches = useCallback((term: string): number => {
    let total = 0;
    for (const [, countFn] of matchCounters.current) {
      total += countFn(term);
    }
    return total;
  }, []);

  const registerMatchCounter = useCallback(
    (id: string, countFn: ExtendedCountFn): (() => void) => {
      matchCounters.current.set(id, countFn);
      return () => {
        matchCounters.current.delete(id);
      };
    },
    [],
  );

  const goToMatch = useCallback(
    async (term: string, absoluteIndex: number): Promise<boolean> => {
      for (const [, fn] of goToMatchFns.current) {
        const result = await fn(term, absoluteIndex);
        if (result) return true;
      }
      return false;
    },
    [],
  );

  const registerGoToMatch = useCallback(
    (id: string, fn: GoToMatchFn): (() => void) => {
      goToMatchFns.current.set(id, fn);
      return () => {
        goToMatchFns.current.delete(id);
      };
    },
    [],
  );

  const contextValue: ExtendedFindContextType = {
    countAllMatches,
    registerMatchCounter,
    goToMatch,
    registerGoToMatch,
  };

  return (
    <ExtendedFindContext.Provider value={contextValue}>
      {children}
    </ExtendedFindContext.Provider>
  );
};

export const useExtendedFind = (): ExtendedFindContextType => {
  const context = useContext(ExtendedFindContext);
  if (!context) {
    throw new Error("useSearch must be used within a SearchProvider");
  }
  return context;
};
