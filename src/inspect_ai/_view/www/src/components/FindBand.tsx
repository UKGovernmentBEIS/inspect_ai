import clsx from "clsx";
import { FC, KeyboardEvent, useCallback, useEffect, useRef } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import { useStore } from "../state/store";
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

  const getParentExpandablePanel = useCallback(
    (selection: Selection): HTMLElement | undefined => {
      let node = selection.anchorNode;
      while (node) {
        if (
          node instanceof HTMLElement &&
          node.classList.contains("expandable-panel")
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

      // Capture the curently focused element so we can restore focus later
      const focusedElement = document.activeElement as HTMLElement;

      // Find the term in the DOM
      let result = await findExtendedInDOM(
        searchTerm,
        back,
        lastFoundItem.current,
        extendedFindTerm,
      );

      const noResultEl = document.getElementById("inspect-find-no-results");
      if (!noResultEl) {
        return;
      }

      // Show "No results" if neither current DOM nor virtual search found anything
      noResultEl.style.opacity = result ? "0" : "1";

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
            parentPanel.style.display = "block";
            parentPanel.style.webkitLineClamp = "";
            parentPanel.style.webkitBoxOrient = "";
          }

          const element = range.startContainer.parentElement;

          if (element) {
            setTimeout(() => {
              element.scrollIntoView({
                behavior: "auto",
                block: "center",
              });
            }, 100);
          }
        }
      }

      focusedElement?.focus();
    },
    [getParentExpandablePanel, extendedFindTerm],
  );

  useEffect(() => {
    setTimeout(() => {
      searchBoxRef.current?.focus();
      searchBoxRef.current?.select();
    }, 10);

    // Block browser find when FindBand is active
    const handleGlobalKeydown = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        // Focus our search box instead
        searchBoxRef.current?.focus();
        searchBoxRef.current?.select();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "g") {
        e.preventDefault();
        e.stopPropagation();
        const back = e.shiftKey;
        // Find next / previous
        handleSearch(back);
      }
    };

    document.addEventListener("keydown", handleGlobalKeydown, true); // Use capture phase

    return () => {
      document.removeEventListener("keydown", handleGlobalKeydown, true);
    };
  }, [handleSearch]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        storeHideFind();
      } else if (e.key === "Enter") {
        handleSearch(e.shiftKey);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "g") {
        e.preventDefault();
        handleSearch(!e.shiftKey);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        searchBoxRef.current?.focus();
        searchBoxRef.current?.select();
      }
    },
    [storeHideFind, handleSearch],
  );

  const showSearch = useCallback(() => {
    handleSearch(true);
  }, [handleSearch]);

  const hideSearch = useCallback(() => {
    handleSearch(false);
  }, [handleSearch]);

  return (
    <div data-unsearchable="true" className={clsx("findBand")}>
      <input
        type="text"
        ref={searchBoxRef}
        placeholder="Find"
        onKeyDown={handleKeyDown}
      />
      <span id="inspect-find-no-results">No results</span>
      <button
        type="button"
        title="Previous match"
        className="btn next"
        onClick={showSearch}
      >
        <i className={ApplicationIcons.arrows.up} />
      </button>
      <button
        type="button"
        title="Next match"
        className="btn prev"
        onClick={hideSearch}
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

        // We mark certain elements as unsearchable (e.g. )
        let isUnsearchable = inUnsearchableElement(range);

        // Also check if it's the same item as last time
        const isSameAsLast = isLastFoundItem(range, lastFoundItem);

        // If this is a valid match (not unsearchable and not same as last), we're done
        if (!isUnsearchable && !isSameAsLast) {
          break;
        }
        // Otherwise continue the loop to find the next match
      }
    } else if (!hasTriedExtendedSearch) {
      // No result in current DOM and haven't tried extended search yet
      hasTriedExtendedSearch = true;

      const foundInVirtual = await extendedFindTerm(
        searchTerm,
        back ? "backward" : "forward",
      );

      if (foundInVirtual) {
        // We found it in the virtual list (which will have scrolled the item
        // into view), so try finding again in the DOM
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
