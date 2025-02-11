import { useCallback, useEffect, useRef } from "react";
import { ApplicationIcons } from "../appearance/icons";
import "./FindBand.css";

interface FindBandProps {
  hideBand: () => void;
}

export const FindBand: React.FC<FindBandProps> = ({ hideBand }) => {
  const searchBoxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTimeout(() => {
      searchBoxRef.current?.focus();
    }, 10);
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
    (back = false) => {
      const searchTerm = searchBoxRef.current?.value ?? "";
      const focusedElement = document.activeElement as HTMLElement;
      // @ts-expect-error: `Window.find` is non-standard
      const result = window.find(
        searchTerm,
        false,
        back,
        false,
        false,
        true,
        false,
      );
      const noResultEl = document.getElementById("inspect-find-no-results");

      if (!noResultEl) return;

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
                behavior: "smooth",
                block: "center",
              });
            }, 100);
          }
        }
      }

      focusedElement?.focus();
    },
    [getParentExpandablePanel],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        hideBand();
      } else if (e.key === "Enter") {
        handleSearch(false);
      }
    },
    [hideBand, handleSearch],
  );

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
        onClick={() => handleSearch(true)}
      >
        <i className={ApplicationIcons.arrows.up} />
      </button>
      <button
        type="button"
        title="Next match"
        className="btn prev"
        onClick={() => handleSearch(false)}
      >
        <i className={ApplicationIcons.arrows.down} />
      </button>
      <button
        type="button"
        title="Close"
        className="btn close"
        onClick={hideBand}
      >
        <i className={ApplicationIcons.close} />
      </button>
    </div>
  );
};
