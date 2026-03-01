import {
  FC,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useStore } from "../state/store";
import { debounce } from "../utils/sync";
import { useExtendedFind } from "./ExtendedFindContext";
import { FindBandUI } from "./FindBandUI";

export const FindBand: FC = () => {
  const searchBoxRef = useRef<HTMLInputElement>(null);
  const storeHideFind = useStore((state) => state.appActions.hideFind);
  const { countAllMatches, goToMatch } = useExtendedFind();
  const currentSearchTerm = useRef<string>("");
  const matchIndexRef = useRef(0);
  const needsCursorRestoreRef = useRef<boolean>(false);
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

  const handleSearch = useCallback(
    async (back = false) => {
      const thisSearchId = ++searchIdRef.current;

      const searchTerm = searchBoxRef.current?.value ?? "";
      if (!searchTerm) {
        // Clear CSS highlight when search term is emptied
        if (CSS?.highlights) {
          CSS.highlights.delete("find-match-all");
          CSS.highlights.delete("find-match-current");
        }
        setMatchCount(null);
        setCurrentMatchIndex(0);
        matchIndexRef.current = 0;
        currentSearchTerm.current = "";
        return;
      }

      // Count total matches (data-level)
      let total: number;
      if (cachedCount.current.term === searchTerm) {
        total = cachedCount.current.count;
      } else {
        total = countAllMatches(searchTerm);
        cachedCount.current = { term: searchTerm, count: total };
      }
      setMatchCount(total);

      if (total === 0) {
        // Clear CSS highlight when search returns 0 results
        if (CSS?.highlights) {
          CSS.highlights.delete("find-match-all");
          CSS.highlights.delete("find-match-current");
        }
        setCurrentMatchIndex(0);
        matchIndexRef.current = 0;
        currentSearchTerm.current = searchTerm;
        return;
      }

      // Compute the target match index
      const isNewTerm = currentSearchTerm.current !== searchTerm;
      let newIndex: number;

      if (isNewTerm) {
        currentSearchTerm.current = searchTerm;
        newIndex = 1;
      } else if (back) {
        newIndex =
          matchIndexRef.current <= 1 ? total : matchIndexRef.current - 1;
      } else {
        newIndex =
          matchIndexRef.current >= total ? 1 : matchIndexRef.current + 1;
      }

      matchIndexRef.current = newIndex;
      setCurrentMatchIndex(newIndex);

      if (searchIdRef.current !== thisSearchId) return;

      const focusedElement = document.activeElement as HTMLElement;

      await goToMatch(searchTerm, newIndex);

      if (searchIdRef.current !== thisSearchId) return;

      focusedElement?.focus();
    },
    [countAllMatches, goToMatch],
  );

  useEffect(() => {
    focusTimeoutRef.current = window.setTimeout(() => {
      searchBoxRef.current?.focus();
      searchBoxRef.current?.select();
    }, 10);

    const mutatedPanels = mutatedPanelsRef.current;
    const focusTimeout = focusTimeoutRef.current;

    return () => {
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
      // Clear the CSS Custom Highlight
      if (CSS?.highlights) {
        CSS.highlights.delete("find-match-all");
        CSS.highlights.delete("find-match-current");
      }
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
      }, 100),
    [handleSearch],
  );

  const handleInputChange = useCallback(() => {
    debouncedSearch();
  }, [debouncedSearch]);

  const handleBeforeInput = useCallback(() => {
    // Clear the restore flag — the user is actively editing,
    // so the cursor is already where they want it.
    needsCursorRestoreRef.current = false;
  }, []);

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

      // Only restore cursor and focus if the input doesn't already have focus.
      // If the user is actively editing in the input, don't move their cursor.
      if (document.activeElement !== input) {
        restoreCursor();
        input.focus();
      }
    };

    document.addEventListener("keydown", handleGlobalKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleGlobalKeyDown, true);
    };
  }, [handleSearch, restoreCursor]);

  const hasHighlightAPI = !!(typeof CSS !== "undefined" && CSS?.highlights && typeof Highlight !== "undefined");

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
      {!hasHighlightAPI && (
        <span className="findBand-no-results">
          Search requires Chrome 105+, Firefox 140+, or Safari 17.2+
        </span>
      )}
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
