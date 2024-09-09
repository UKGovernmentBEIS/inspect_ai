import { html } from "htm/preact";
import { useEffect, useRef } from "preact/hooks";
import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

export const FindBand = ({ hideBand }) => {
  const searchBoxRef = useRef();
  useEffect(() => {
    searchBoxRef.current.focus();
  }, []);

  const searchTerm = () => {
    return searchBoxRef.current.value;
  };

  const search = (term, back) => {
    const parentExpandablePanel = (selection) => {
      // Get the anchor node (the starting node of the selection)
      let node = selection.anchorNode;

      // Traverse up the DOM tree to find the parent with the class 'expandable-panel'
      let expandablePanelEl = undefined;
      while (node) {
        if (node.classList && node.classList.contains("expandable-panel")) {
          expandablePanelEl = node;
          break;
        }
        node = node.parentElement;
      }
      return expandablePanelEl;
    };

    // capture what is focused
    const focusedElement = document.activeElement;
    const result = window.find(term, false, !!back, false, false, true, false);
    const noResultEl = window.document.getElementById(
      "inspect-find-no-results",
    );
    if (result) {
      noResultEl.style.opacity = 0;
      const selection = window.getSelection();
      if (selection.rangeCount > 0) {
        // See if the parent is an expandable panel and expand it
        const parentPanel = parentExpandablePanel(selection);
        if (parentPanel) {
          parentPanel.style.display = "block";
          parentPanel.style["-webkit-line-clamp"] = "";
          parentPanel.style["-webkit-box-orient"] = "";
        }

        const range = selection.getRangeAt(0);
        setTimeout(() => {
          const element = range.startContainer.parentElement;
          element.scrollIntoView({
            behavior: "smooth", // Optional: adds a smooth scrolling animation
            block: "center", // Optional: scrolls so the element is centered in the view
          });
        }, 100);
      }
    } else {
      noResultEl.style.opacity = 1;
    }

    // Return focus to the previously focused element
    if (focusedElement) {
      focusedElement.focus();
    }
  };

  return html`<div
    style=${{
      position: "absolute",
      top: 0,
      right: 0,
      marginRight: "20%",
      zIndex: "1060",
      color: "var(--inspect-find-foreground)",
      backgroundColor: "var(--inspect-find-background)",
      fontSize: "0.9rem",
      display: "grid",
      gridTemplateColumns: "auto auto auto auto auto",
      columnGap: "0.2em",
      padding: "0.2rem",
      borderBottom: "solid 1px var(--bs-light-border-subtle)",
      borderLeft: "solid 1px var(--bs-light-border-subtle)",
      borderRight: "solid 1px var(--bs-light-border-subtle)",
      boxShadow: "var(--bs-box-shadow)",
    }}
  >
    <input
      type="text"
      ref=${searchBoxRef}
      style=${{
        height: "2em",
        fontSize: "0.9em",
        margin: "0.1rem",
        outline: "none",
        border: "solid 1px var(--inspect-input-border)",
        color: "var(--inspect-input-foreground)",
        background: "var(--inspect-input-background)",
      }}
      placeholder="Find"
      onkeydown=${(e) => {
        if (e.key === "Escape") {
          hideBand();
        } else if (e.key === "Enter") {
          search(searchTerm());
        }
      }}
    />
    <span
      id="inspect-find-no-results"
      style=${{
        fontSize: FontSize.base,
        opacity: 0,
        marginTop: "auto",
        marginBottom: "auto",
        marginRight: "0.5em",
      }}
      >No results</span
    >
    <button
      title="Previous match"
      style=${{ padding: 0, fontSize: FontSize.larger }}
      class="btn"
      onclick=${() => {
        search(searchTerm(), true);
      }}
    >
      <i class=${ApplicationIcons.arrows.up}></i>
    </button>
    <button
      title="Next match"
      style=${{ padding: 0, fontSize: FontSize.larger }}
      class="btn"
      onclick=${() => {
        search(searchTerm());
      }}
    >
      <i class=${ApplicationIcons.arrows.down}></i>
    </button>
    <button
      title="Close"
      style=${{
        padding: 0,
        fontSize: FontSize["title-secondary"],
        marginTop: "-0.1rem",
        marginBottom: "-0.1rem",
      }}
      class="btn"
      onclick=${() => hideBand()}
    >
      <i class=${ApplicationIcons.close}></i>
    </button>
  </div>`;
};
