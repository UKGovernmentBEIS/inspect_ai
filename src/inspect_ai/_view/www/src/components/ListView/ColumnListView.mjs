//@ts-check
import { html } from "htm/preact";

import { ListView } from "./ListView.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";

/**
 * @template T
 * Renders the ToolCallView component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("./Types.mjs").Row<T>[]} props.rows - The row data to be rendered.
 * @param {import("./Types.mjs").Renderer<T>} props.renderer - The row data to be rendered.
 * @param {string[]} props.columns - The column headers
 * @param {string[]} props.columnWidths - The columnSizes
 * @param {number} props.selectedIndex - The selected index
 * @param {(index: number) => void} props.onSelectedIndex - Function to set the selected index
 * @param {(item: T) => void} props.onShowItem - Function that will be called when an item should be shown
 * @param {Object} [props.style] - Optional styles to apply to the panel.
 *
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const ColumnListView = ({
  rows,
  renderer,
  columns,
  columnWidths,
  selectedIndex,
  onSelectedIndex,
  onShowItem,
  style,
}) => {
  return html`
    <div style=${{ display: "grid", gridTemplateRows: "max-content 1fr" }}>
      <div
        style=${{
          display: "grid",
          gridTemplateColumns: columnWidths.join(" "),
          width: "100%",
          padding: "0.5em 1em",
          columnGap: "0.5em",
          backgroundColor: "var(--bs-light)",
          borderBottom: "solid var(--bs-light-border-subtle) 1px",
          fontSize: FontSize.smaller,
        }}
        tabindex="0"
      >
        ${columns.map((col, index) => {
          if (index < columns.length - 1) {
            return html` <div
              style=${{ display: "grid", gridTemplateColumns: "1fr 10px" }}
            >
              <div>${col}</div>
              <div
                style=${{
                  borderRight: "solid var(--bs-dark-border-subtle) 1px",
                  cursor: "pointer",
                }}
              ></div>
            </div>`;
          } else {
            return html`<div>${col}</div>`;
          }
        })}
      </div>
      <${ListView}
        rows=${rows}
        renderer=${renderer}
        selectedIndex=${selectedIndex}
        onSelectedIndex=${onSelectedIndex}
        onShowItem=${onShowItem}
        tabIndex="0"
        style=${style}
      />
    </div>
  `;
};
