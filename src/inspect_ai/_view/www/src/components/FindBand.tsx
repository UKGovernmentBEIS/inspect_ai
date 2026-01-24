import clsx from "clsx";
import {
  FC,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import { useStore } from "../state/store";
import { findScrollableParent, scrollRangeToCenter } from "../utils/dom";
import { debounce } from "../utils/sync";
import { useExtendedFind } from "./ExtendedFindContext";
import "./FindBand.css";

interface FindBandProps {}

const findConfig = {
  caseSensitive: false,
  wrapAround: false,
  wholeWord: false,
  searchInFrames: false,
  showDialog: false,
};

export const FindBand: FC<FindBandProps> = () => {
  const searchBoxRef = useRef<HTMLInputElement>(null);
  const storeHideFind = useStore((state) => state.appActions.hideFind);
  const { extendedFindTerm } = useExtendedFind();
  const lastFoundItem = useRef<{
    text: string;
    offset: number;
    parentElement: Element;
  } | null>(null);
  const currentSearchTerm = useRef<string>("");
  const needsCursorRestoreRef = useRef<boolean>(false);
  const lastNoResultTerm = useRef<string>("");
  const lastNoResultDirection = useRef<boolean | null>(null);
  const scrollTimeoutRef = useRef<number | null>(null);
  const focusTimeoutRef = useRef<number | null>(null);
  const searchIdRef = useRef(0);
  const mutatedPanelsRef = useRef<
    Map<
      HTMLElement,
      {
        display: string;
        maxHeight: string;
        webkitLineClamp: string;
        webkitBoxOrient: string;
      }
    >
  >(new Map());

  const getParentExpandablePanel = useCallback(
    (selection: Selection): HTMLElement | undefined => {
      let node = selection.anchorNode;
      while (node) {
        if (
          node instanceof HTMLElement &&
          node.hasAttribute("data-expandable-panel")
        ) {
          return node;
        }
        node = node.parentElement;
      }
      return undefined;
    },
    [],
  );

  const handleSearch = useCallback(
    async (back = false) => {
      // Track this search to handle race conditions
      const thisSearchId = ++searchIdRef.current;

      // The search term
      const searchTerm = searchBoxRef.current?.value ?? "";
      if (!searchTerm) {
        return;
      }

      // Reset last found item if search term changed
      if (currentSearchTerm.current !== searchTerm) {
        lastFoundItem.current = null;
        currentSearchTerm.current = searchTerm;
      }

      const noResultEl = document.getElementById("inspect-find-no-results");

      // Skip search if we already know this term has no results in this direction
      if (
        lastNoResultTerm.current &&
        searchTerm.startsWith(lastNoResultTerm.current) &&
        lastNoResultDirection.current === back
      ) {
        if (noResultEl) {
          noResultEl.style.opacity = "1";
          noResultEl.setAttribute("aria-hidden", "false");
        }
        return;
      }

      // Clear no-result cache if search term changed or direction changed
      if (
        lastNoResultTerm.current &&
        (!searchTerm.startsWith(lastNoResultTerm.current) ||
          lastNoResultDirection.current !== back)
      ) {
        lastNoResultTerm.current = "";
        lastNoResultDirection.current = null;
      }

      // Capture the curently focused element so we can restore focus later
      const focusedElement = document.activeElement as HTMLElement;

      // Save current selection before search (window.find may disturb it)
      const selection = window.getSelection();
      let savedRange: Range | null = null;
      if (selection && selection.rangeCount > 0) {
        savedRange = selection.getRangeAt(0).cloneRange();
      }

      // Save scroll position before search (window.find may scroll during search)
      const savedScrollParent = savedRange
        ? findScrollableParent(savedRange.startContainer.parentElement)
        : null;
      const savedScrollTop = savedScrollParent?.scrollTop ?? 0;

      // Find the term in the DOM
      let result = await findExtendedInDOM(
        searchTerm,
        back,
        lastFoundItem.current,
        extendedFindTerm,
      );

      if (!noResultEl) {
        return;
      }

      // If a newer search has started, discard this result to avoid race conditions
      if (searchIdRef.current !== thisSearchId) {
        return;
      }

      // Show "No results" if neither current DOM nor virtual search found anything
      noResultEl.style.opacity = result ? "0" : "1";
      noResultEl.setAttribute("aria-hidden", result ? "true" : "false");

      lastNoResultTerm.current = result ? "" : searchTerm;
      lastNoResultDirection.current = result ? null : back;

      // If no result found, restore the previous selection so we stay on current match
      if (!result && savedRange) {
        const sel = window.getSelection();
        if (sel) {
          sel.removeAllRanges();
          sel.addRange(savedRange);
        }
        if (savedScrollParent) {
          savedScrollParent.scrollTop = savedScrollTop;
        }
      }

      if (result) {
        const selection = window.getSelection();
        if (selection && selection.rangeCount > 0) {
          // Remember this item for next time
          const range = selection.getRangeAt(0);
          const parentElement =
            range.startContainer.parentElement ||
            (range.commonAncestorContainer as Element);
          lastFoundItem.current = {
            text: range.toString(),
            offset: range.startOffset,
            parentElement,
          };

          const parentPanel = getParentExpandablePanel(selection);
          if (parentPanel) {
            // Save original styles if not already tracked
            if (!mutatedPanelsRef.current.has(parentPanel)) {
              mutatedPanelsRef.current.set(parentPanel, {
                display: parentPanel.style.display,
                maxHeight: parentPanel.style.maxHeight,
                webkitLineClamp: parentPanel.style.webkitLineClamp,
                webkitBoxOrient: parentPanel.style.webkitBoxOrient,
              });
            }
            parentPanel.style.display = "block";
            parentPanel.style.maxHeight = "none";
            parentPanel.style.webkitLineClamp = "";
            parentPanel.style.webkitBoxOrient = "";
          }

          // Scroll the selection into view (with a small delay for DOM updates)
          if (scrollTimeoutRef.current !== null) {
            window.clearTimeout(scrollTimeoutRef.current);
          }
          scrollTimeoutRef.current = window.setTimeout(() => {
            scrollRangeToCenter(range);
          }, 100);
        }
      }

      focusedElement?.focus();
    },
    [getParentExpandablePanel, extendedFindTerm],
  );

  useEffect(() => {
    focusTimeoutRef.current = window.setTimeout(() => {
      searchBoxRef.current?.focus();
      searchBoxRef.current?.select();
    }, 10);

    // Capture ref values for cleanup
    const mutatedPanels = mutatedPanelsRef.current;
    const scrollTimeout = scrollTimeoutRef.current;
    const focusTimeout = focusTimeoutRef.current;

    return () => {
      if (scrollTimeout !== null) {
        window.clearTimeout(scrollTimeout);
      }
      if (focusTimeout !== null) {
        window.clearTimeout(focusTimeout);
      }
      // Restore original styles on mutated expandable panels
      mutatedPanels.forEach((originalStyles, panel) => {
        panel.style.display = originalStyles.display;
        panel.style.maxHeight = originalStyles.maxHeight;
        panel.style.webkitLineClamp = originalStyles.webkitLineClamp;
        panel.style.webkitBoxOrient = originalStyles.webkitBoxOrient;
      });
      mutatedPanels.clear();
    };
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        storeHideFind();
      } else if (e.key === "Enter") {
        void handleSearch(e.shiftKey);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "g") {
        e.preventDefault();
        void handleSearch(e.shiftKey);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        searchBoxRef.current?.focus();
        searchBoxRef.current?.select();
      }
    },
    [storeHideFind, handleSearch],
  );

  const findPrevious = useCallback(() => {
    void handleSearch(true);
  }, [handleSearch]);

  const findNext = useCallback(() => {
    void handleSearch(false);
  }, [handleSearch]);

  const restoreCursor = useCallback(() => {
    if (!needsCursorRestoreRef.current) return;
    needsCursorRestoreRef.current = false;
    const input = searchBoxRef.current;
    if (input) {
      const len = input.value.length;
      input.setSelectionRange(len, len);
    }
  }, []);

  // Debounced auto-search as you type
  const debouncedSearch = useMemo(
    () =>
      debounce(async () => {
        if (!searchBoxRef.current) return;
        await handleSearch(false);
        // Mark for cursor restore on next keypress (keeps find highlight visible)
        needsCursorRestoreRef.current = true;
      }, 300),
    [handleSearch],
  );

  const handleInputChange = useCallback(() => {
    debouncedSearch();
  }, [debouncedSearch]);

  const handleBeforeInput = useCallback(() => {
    // Only restore cursor if no text is selected
    // This preserves native browser behavior (typing replaces selected text)
    const input = searchBoxRef.current;
    if (input) {
      const hasSelection = input.selectionStart !== input.selectionEnd;
      if (!hasSelection) {
        restoreCursor();
      }
    }
  }, [restoreCursor]);

  // Consolidated global keyboard handler
  useEffect(() => {
    const handleGlobalKeyDown = (e: globalThis.KeyboardEvent) => {
      // F3: Find next/previous
      if (e.key === "F3") {
        e.preventDefault();
        void handleSearch(e.shiftKey);
        return;
      }

      // Ctrl/Cmd+F: Focus search box (block browser find)
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        searchBoxRef.current?.focus();
        searchBoxRef.current?.select();
        return;
      }

      // Ctrl/Cmd+G: Find next/previous
      if ((e.ctrlKey || e.metaKey) && e.key === "g") {
        e.preventDefault();
        e.stopPropagation();
        void handleSearch(e.shiftKey);
        return;
      }

      // Skip if modifier keys are held (except for handled shortcuts above)
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      // Auto-focus input when typing printable characters or backspace/delete
      if (e.key.length !== 1 && e.key !== "Backspace" && e.key !== "Delete")
        return;

      const input = searchBoxRef.current;
      if (!input) return;

      // Only restore cursor if no text is selected
      // This preserves native browser behavior (typing replaces selected text)
      const hasSelection = input.selectionStart !== input.selectionEnd;
      if (!hasSelection) {
        restoreCursor();
      }

      if (document.activeElement !== input) {
        input.focus();
      }
    };

    // Use capture phase to intercept browser's native find dialog
    document.addEventListener("keydown", handleGlobalKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [handleSearch, restoreCursor]);

  return (
    <div data-unsearchable="true" className={clsx("findBand")}>
      <input
        type="text"
        ref={searchBoxRef}
        placeholder="Find"
        onKeyDown={handleKeyDown}
        onBeforeInput={handleBeforeInput}
        onChange={handleInputChange}
      />
      <span id="inspect-find-no-results" aria-hidden="true">
        No results
      </span>
      <button
        type="button"
        title="Previous match"
        className="btn next"
        onClick={findPrevious}
      >
        <i className={ApplicationIcons.arrows.up} />
      </button>
      <button
        type="button"
        title="Next match"
        className="btn prev"
        onClick={findNext}
      >
        <i className={ApplicationIcons.arrows.down} />
      </button>
      <button
        type="button"
        title="Close"
        className="btn close"
        onClick={storeHideFind}
      >
        <i className={ApplicationIcons.close} />
      </button>
    </div>
  );
};
async function findExtendedInDOM(
  searchTerm: string,
  back: boolean,
  lastFoundItem: {
    text: string;
    offset: number;
    parentElement: Element;
  } | null,
  extendedFindTerm: (
    term: string,
    direction: "forward" | "backward",
  ) => Promise<boolean>,
) {
  let result = false;
  let attempts = 0;
  let hasTriedExtendedSearch = false;
  const maxAttempts = 25;

  do {
    // @ts-expect-error: `Window.find` is non-standard
    result = window.find(
      searchTerm,
      findConfig.caseSensitive,
      back,
      findConfig.wrapAround,
      findConfig.wholeWord,
      findConfig.searchInFrames,
      findConfig.showDialog,
    );

    if (result) {
      // We have a result, check whether it is valid (not in unsearchable
      // element and not the same as last). If is isn't valid, ignore it
      // and continue the loop to find the next match.
      const selection = window.getSelection();
      if (selection && selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);

        // We mark certain elements as unsearchable
        const isUnsearchable = inUnsearchableElement(range);

        // Also check if it's the same item as last time
        const isSameAsLast = isLastFoundItem(range, lastFoundItem);

        // If this is a valid match (not unsearchable and not same as last), we're done
        if (!isUnsearchable && !isSameAsLast) {
          break;
        }

        // If we found the same match as last time, there are no new results
        if (isSameAsLast) {
          return false;
        }
        // Otherwise continue the loop to find the next match (skip unsearchable)
      }
    } else if (!hasTriedExtendedSearch) {
      // No result in current DOM and haven't tried extended search yet
      hasTriedExtendedSearch = true;

      const foundInVirtual = await extendedFindTerm(
        searchTerm,
        back ? "backward" : "forward",
      );

      if (foundInVirtual) {
        // Found in virtual list (which will have scrolled the item into view),
        // so try finding again in the DOM
      } else {
        // Extended search failed, no more options
        break;
      }
    } else {
      // No result and already tried extended search
      break;
    }

    attempts++;
  } while (attempts < maxAttempts);
  return result;
}

function isLastFoundItem(
  range: Range,
  lastFoundItem: {
    text: string;
    offset: number;
    parentElement: Element;
  } | null,
) {
  if (!lastFoundItem) return false;

  const currentText = range.toString();
  const currentOffset = range.startOffset;
  const currentParentElement =
    range.startContainer.parentElement ||
    (range.commonAncestorContainer as Element);

  return (
    currentText === lastFoundItem.text &&
    currentOffset === lastFoundItem.offset &&
    currentParentElement === lastFoundItem.parentElement
  );
}

function inUnsearchableElement(range: Range) {
  let element: Element | null = selectionParentElement(range);

  // Check if this match is inside an unsearchable element
  let isUnsearchable = false;
  while (element) {
    if (
      element.hasAttribute("data-unsearchable") ||
      getComputedStyle(element).userSelect === "none"
    ) {
      isUnsearchable = true;
      break;
    }
    element = element.parentElement;
  }
  return isUnsearchable;
}

function selectionParentElement(range: Range) {
  let element: Element | null = null;

  if (range.startContainer.nodeType === Node.ELEMENT_NODE) {
    // This is a direct element
    element = range.startContainer as Element;
  } else {
    // This isn't an element, try its parent
    element = range.startContainer.parentElement;
  }

  // Still not found, try the common ancestor container
  if (
    !element &&
    range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
  ) {
    element = range.commonAncestorContainer as Element;
  } else if (!element && range.commonAncestorContainer.parentElement) {
    element = range.commonAncestorContainer.parentElement;
  }
  return element;
}
