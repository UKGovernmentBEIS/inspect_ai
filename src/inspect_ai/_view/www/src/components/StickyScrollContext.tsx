import { createContext, useContext, RefObject } from "react";

/**
 * Context for providing scroll container ref to sticky scroll observers.
 * Used by useStickyObserver hook to properly detect when elements are stuck.
 */
const StickyScrollContext = createContext<RefObject<HTMLElement | null> | null>(
  null,
);

export const StickyScrollProvider = StickyScrollContext.Provider;

export const useStickyScrollContainer = () => useContext(StickyScrollContext);
