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

  useEffect(() => {
    setTimeout(() => {
      searchBoxRef.current?.focus();
    }, 10);

    // Block browser find when FindBand is active
    const handleGlobalKeydown = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        e.stopPropagation();
        // Focus our search box instead
        searchBoxRef.current?.focus();
      }
    };

    document.addEventListener("keydown", handleGlobalKeydown, true); // Use capture phase

    return () => {
      document.removeEventListener("keydown", handleGlobalKeydown, true);
    };
  }, []);

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

      // Capture the curently focused element so we can restore focus later
      const focusedElement = document.activeElement as HTMLElement;

      // First try searching current DOM
      // @ts-expect-error: `Window.find` is non-standard
      let result = window.find(
        searchTerm,
        findConfig.caseSensitive,
        back,
        findConfig.wrapAround,
        findConfig.wholeWord,
        findConfig.searchInFrames,
        findConfig.showDialog,
      );
      console.log("Base search result:", result);

      // If no results in current DOM, try virtual content
      if (!result) {
        console.log("Extended search");
        const foundInVirtual = await extendedFindTerm(
          searchTerm,
          back ? "backward" : "forward",
        );
        console.log("Extended search result", result);

        if (foundInVirtual) {
          console.log("Found in extended search");
          // Content should now be rendered, try window.find again
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
          console.log("Secondary find result:", result);
        }
      }

      const noResultEl = document.getElementById("inspect-find-no-results");
      if (!noResultEl) return;

      // Show "No results" if neither current DOM nor virtual search found anything
      noResultEl.style.opacity = result ? "0" : "1";

      if (result) {
        const selection = window.getSelection();
        if (selection && selection.rangeCount > 0) {
          const parentPanel = getParentExpandablePanel(selection);
          if (parentPanel) {
            parentPanel.style.display = "block";
            parentPanel.style.webkitLineClamp = "";
            parentPanel.style.webkitBoxOrient = "";
          }

          const range = selection.getRangeAt(0);
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

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        storeHideFind();
      } else if (e.key === "Enter") {
        handleSearch(false);
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
    <div className="findBand">
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
