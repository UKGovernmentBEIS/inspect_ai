import clsx from "clsx";
import {
  FC,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
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
  const { extendedFindTerm, countAllMatches } = useExtendedFind();
  const lastFoundItem = useRef<{
    text: string;
    offset: number;
    parentElement: Element;
  } | null>(null);
  const currentSearchTerm = useRef<string>("");
  const needsCursorRestoreRef = useRef<boolean>(false);
  const scrollTimeoutRef = useRef<number | null>(null);
  const focusTimeoutRef = useRef<number | null>(null);
  const searchIdRef = useRef(0);
  const cachedCount = useRef<{ term: string; count: number }>({
    term: "",
    count: 0,
  });
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

  const [matchCount, setMatchCount] = useState<number | null>(null);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);

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
      const thisSearchId = ++searchIdRef.current;

      const searchTerm = searchBoxRef.current?.value ?? "";
      if (!searchTerm) {
        setMatchCount(null);
        setCurrentMatchIndex(0);
        return;
      }

      if (currentSearchTerm.current !== searchTerm) {
        lastFoundItem.current = null;
        currentSearchTerm.current = searchTerm;
        setCurrentMatchIndex(0);
      }

      let total: number;
      if (cachedCount.current.term === searchTerm) {
        total = cachedCount.current.count;
      } else {
        total = countAllMatches(searchTerm);
        cachedCount.current = { term: searchTerm, count: total };
      }
      setMatchCount(total);

      if (total === 0) {
        setCurrentMatchIndex(0);
        return;
      }

      const focusedElement = document.activeElement as HTMLElement;

      const selection = window.getSelection();
      let savedRange: Range | null = null;
      if (selection && selection.rangeCount > 0) {
        savedRange = selection.getRangeAt(0).cloneRange();
      }

      const savedScrollParent = savedRange
        ? findScrollableParent(savedRange.startContainer.parentElement)
        : null;
      const savedScrollTop = savedScrollParent?.scrollTop ?? 0;

      const result = await findExtendedInDOM(
        searchTerm,
        back,
        lastFoundItem.current,
        extendedFindTerm,
      );

      if (searchIdRef.current !== thisSearchId) {
        return;
      }

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
          const range = selection.getRangeAt(0);
          const parentElement =
            range.startContainer.parentElement ||
            (range.commonAncestorContainer as Element);
          const isNewMatch = !isLastFoundItem(range, lastFoundItem.current);
          lastFoundItem.current = {
            text: range.toString(),
            offset: range.startOffset,
            parentElement,
          };

          if (isNewMatch) {
            setCurrentMatchIndex((prev) => {
              if (back) {
                return prev <= 1 ? total : prev - 1;
              } else {
                return prev >= total ? 1 : prev + 1;
              }
            });
          }

          const parentPanel = getParentExpandablePanel(selection);
          if (parentPanel) {
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
    [getParentExpandablePanel, extendedFindTerm, countAllMatches],
  );

  useEffect(() => {
    focusTimeoutRef.current = window.setTimeout(() => {
      searchBoxRef.current?.focus();
      searchBoxRef.current?.select();
    }, 10);

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

      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.key.length !== 1 && e.key !== "Backspace" && e.key !== "Delete")
        return;

      const input = searchBoxRef.current;
      if (!input) return;

      const hasSelection = input.selectionStart !== input.selectionEnd;
      if (!hasSelection) {
        restoreCursor();
      }

      if (document.activeElement !== input) {
        input.focus();
      }
    };

    document.addEventListener("keydown", handleGlobalKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [handleSearch, restoreCursor]);

  const matchCountLabel = useMemo(() => {
    if (matchCount === null) return null;
    if (matchCount === 0) return "No results";
    return `${currentMatchIndex} of ${matchCount}`;
  }, [matchCount, currentMatchIndex]);

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
      {matchCountLabel !== null && (
        <span
          className={clsx(
            "findBand-match-count",
            matchCount === 0 && "findBand-no-results",
          )}
        >
          {matchCountLabel}
        </span>
      )}
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
function windowFind(searchTerm: string, back: boolean): boolean {
  // @ts-expect-error: `Window.find` is non-standard
  return window.find(
    searchTerm,
    findConfig.caseSensitive,
    back,
    findConfig.wrapAround,
    findConfig.wholeWord,
    findConfig.searchInFrames,
    findConfig.showDialog,
  ) as boolean;
}

function positionSelectionForWrap(back: boolean): void {
  if (!back) return;
  const sel = window.getSelection();
  if (sel) {
    const range = document.createRange();
    range.selectNodeContents(document.body);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
  }
}

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
  let hasTriedExtendedSearch = false;
  let extendedSearchSucceeded = false;
  const maxAttempts = 25;

  for (let attempts = 0; attempts < maxAttempts; attempts++) {
    result = windowFind(searchTerm, back);

    if (result) {
      const selection = window.getSelection();
      if (selection && selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        const isUnsearchable = inUnsearchableElement(range);
        const isSameAsLast = isLastFoundItem(range, lastFoundItem);

        if (!isUnsearchable && !isSameAsLast) {
          break;
        }

        if (isSameAsLast) {
          if (!hasTriedExtendedSearch) {
            hasTriedExtendedSearch = true;
            window.getSelection()?.removeAllRanges();

            const foundInVirtual = await extendedFindTerm(
              searchTerm,
              back ? "backward" : "forward",
            );

            if (foundInVirtual) {
              extendedSearchSucceeded = true;
              continue;
            }
          }

          if (extendedSearchSucceeded) {
            // Extended search scrolled to new content but old match is still in DOM.
            // Collapse past it so windowFind advances to the new match.
            const sel = window.getSelection();
            if (sel?.rangeCount) {
              sel.getRangeAt(0).collapse(!back);
            }
          } else {
            window.getSelection()?.removeAllRanges();
            positionSelectionForWrap(back);
          }

          result = windowFind(searchTerm, back);
          if (result) {
            const sel = window.getSelection();
            if (sel && sel.rangeCount > 0) {
              const r = sel.getRangeAt(0);
              if (inUnsearchableElement(r)) {
                continue;
              }
            }
          }
          break;
        }
      }
    } else if (!hasTriedExtendedSearch) {
      hasTriedExtendedSearch = true;
      window.getSelection()?.removeAllRanges();

      const foundInVirtual = await extendedFindTerm(
        searchTerm,
        back ? "backward" : "forward",
      );

      if (foundInVirtual) {
        extendedSearchSucceeded = true;
        continue;
      }

      positionSelectionForWrap(back);
      result = windowFind(searchTerm, back);
      if (result) {
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const r = sel.getRangeAt(0);
          if (inUnsearchableElement(r)) {
            continue;
          }
        }
      }
      break;
    } else {
      break;
    }
  }

  if (result) {
    const sel = window.getSelection();
    if (sel?.rangeCount && inUnsearchableElement(sel.getRangeAt(0))) {
      sel.removeAllRanges();
      result = false;
    }
  }

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
