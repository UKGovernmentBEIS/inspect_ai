import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import { useRef } from "preact/hooks";

/**
 * Renders the Sample Filter Control
 *
 * @param {Object} props - The parameters for the component.
 * @param {(filter: import("../../Types.mjs").ScoreFilter) => void} props.filterChanged - Filter changed function
 * @param {import("../../Types.mjs").ScoreFilter} props.filter - Capabilities of the application host
 * @param {string | undefined} props.filterError - The error in the filter expression, if any.
 * @returns {import("preact").JSX.Element | string} The TranscriptView component.
 */
export const SampleFilter = ({ filter, filterError, filterChanged }) => {
  const inputRef = useRef(null);
  const tooltip = filterError
    ? `${filterError}\n\n${filterTooltip}`
    : filterTooltip;

  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="sample-filter-label"
        style=${{
          alignSelf: "center",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginRight: "0.3em",
          marginLeft: "0.2em",
        }}
        >Filter:</span
      >
      <div style=${{ position: "relative", width: "300px", display: "flex" }}>
        <input
          type="text"
          id="sample-filter-input"
          class="form-control"
          aria-label=".sample-filter-label"
          value=${filter.value || ""}
          autocomplete="off"
          autocorrect="off"
          autocapitalize="off"
          spellcheck=${false}
          placeholder="Filter expression..."
          title=${tooltip}
          style=${{
            width: "100%",
            fontSize: FontSize.smaller,
            borderColor: filterError ? "red" : undefined,
            paddingRight: "1.5em",
          }}
          onInput=${(e) => {
            filterChanged({
              value: e.currentTarget.value,
            });
          }}
          ref=${inputRef}
        />
        ${filter.value &&
        html`
          <button
            class="btn btn-link"
            style=${{
              position: "absolute",
              right: "0.3em",
              top: "50%",
              transform: "translateY(-50%)",
              padding: "0",
              fontSize: FontSize.smaller,
              textDecoration: "none",
              ...TextStyle.secondary,
            }}
            onClick=${() => {
              filterChanged({
                value: "",
              });
              inputRef.current?.focus();
            }}
            title="Clear filter"
          >
            ✕
          </button>
        `}
      </div>
    </div>
  `;
};

const filterTooltip = `
Filter samples by scores. Supported expressions:
  • Arithmetic: +, -, *, /, mod, ^
  • Comparison: <, <=, >, >=, ==, !=, including chain comparisons, e.g. “10 <= x < 20”
  • Boolean: and, or, not
  • Regex matching: ~= (case-sensitive)
  • Set operations: in, not in; e.g. “x in (1, 2, 3)”
  • Functions: min, max, abs, round, floor, ceil, sqrt, log, log2, log10
Click on the score name above to add it to the filter.
`.trim();
