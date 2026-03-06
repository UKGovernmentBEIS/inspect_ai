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

// Find will call this when an extended find is requested
export type ExtendedFindFn = (
  term: string,
  direction: "forward" | "backward",
  onContentReady: () => void,
) => Promise<boolean>;

// Count total matches across all data items
export type ExtendedCountFn = (term: string) => number;

// The context provides an extended search function and a way for the active
// virtual lists to register themselves.
interface ExtendedFindContextType {
  extendedFindTerm: (
    term: string,
    direction: "forward" | "backward",
  ) => Promise<boolean>;
  registerVirtualList: (id: string, searchFn: ExtendedFindFn) => () => void;
  countAllMatches: (term: string) => number;
  registerMatchCounter: (id: string, countFn: ExtendedCountFn) => () => void;
}

const ExtendedFindContext = createContext<ExtendedFindContextType | null>(null);

interface ExtendedFindProviderProps {
  children: ReactNode;
}

export const ExtendedFindProvider = ({
  children,
}: ExtendedFindProviderProps) => {
  const virtualLists = useRef<Map<string, ExtendedFindFn>>(new Map());
  const matchCounters = useRef<Map<string, ExtendedCountFn>>(new Map());

  const extendedFindTerm = useCallback(
    async (
      term: string,
      direction: "forward" | "backward",
    ): Promise<boolean> => {
      for (const [, searchFn] of virtualLists.current) {
        const found = await new Promise<boolean>((resolve) => {
          let callbackFired = false;

          const onContentReady = () => {
            if (!callbackFired) {
              callbackFired = true;
              resolve(true);
            }
          };

          searchFn(term, direction, onContentReady)
            .then((found) => {
              if (!found && !callbackFired) {
                callbackFired = true;
                resolve(false);
              }
            })
            .catch(() => {
              if (!callbackFired) {
                callbackFired = true;
                resolve(false);
              }
            });
        });

        if (found) {
          return true;
        }
      }
      return false;
    },
    [],
  );

  const registerVirtualList = useCallback(
    (id: string, searchFn: ExtendedFindFn): (() => void) => {
      virtualLists.current.set(id, searchFn);
      return () => {
        virtualLists.current.delete(id);
      };
    },
    [],
  );

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

  const contextValue: ExtendedFindContextType = {
    extendedFindTerm,
    registerVirtualList,
    countAllMatches,
    registerMatchCounter,
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
