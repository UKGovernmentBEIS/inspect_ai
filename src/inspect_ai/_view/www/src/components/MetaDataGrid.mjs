// @ts-check
import { html } from "htm/preact";
import { RenderedContent } from "./RenderedContent.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";

/**
 * Renders the MetaDataView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the table element.
 * @param {string} [props.classes] - Additional class names for the table element.
 * @param {Object} [props.style] - Inline styles for the table element.
 * @param {Object[]|Record<string, string>} props.entries - The metadata entries to display.
 * @param {Object} [props.context] - Context for rendering the entries.
 * @param {boolean} [props.expanded] - Whether to render the entries in expanded mode.
 * @param {boolean} [props.plain] - Whether to render the entries in plain mode.
 * @param {boolean} [props.compact] - Whether to render the table in compact mode.
 * @returns {import("preact").JSX.Element} The component.
 */
export const MetaDataGrid = ({
  id,
  entries,
  classes,
  context,
  style,
  expanded,
  plain,
}) => {
  const baseId = "metadata-grid";

  const cellKeyStyle = {
    fontWeight: "400",
    whiteSpace: "nowrap",
    ...TextStyle.label,
    ...TextStyle.secondary,
  };
  const cellValueStyle = {
    whiteSpace: "pre-wrap",
    wordWrap: "anywhere",
    fontSize: FontSize.small,
  };
  const cellKeyTextStyle = {
    fontSize: FontSize.small,
  };

  // entries can be either a Record<string, stringable>
  // or an array of record with name/value on way in
  // but coerce to array of records for order
  /**
   * Ensure the proper type for entries
   *
   * @param {Object[]|Record<string, string>} entries - The metadata entries to display.
   * @returns {Record<string, unknown>[]} The component.
   */
  const entryRecords = (entries) => {
    if (!entries) {
      return [];
    }

    if (!Array.isArray(entries)) {
      return Object.entries(entries || {}).map(([key, value]) => {
        return { name: key, value };
      });
    } else {
      return entries;
    }
  };

  const entryEls = entryRecords(entries).map((entry, index) => {
    const id = `${baseId}-value-${index}`;
    return html`
      <div
        style=${{
          gridColumn: "1 / -1",
          borderBottom: `${!plain ? "solid 1px var(--bs-light-border-subtle" : ""}`,
        }}
      ></div>
      <div
        class="${baseId}-key"
        style=${{ ...cellKeyStyle, ...cellKeyTextStyle }}
      >
        ${entry.name}
      </div>
      <div class="${baseId}-value" style=${{ ...cellValueStyle }}>
        <${RenderedContent}
          id=${id}
          entry=${entry}
          context=${context}
          options=${{ expanded }}
        />
      </div>
    `;
  });

  return html`<div
    ...${{ id }}
    class="${classes || ""}"
    style=${{
      display: "grid",
      gridTemplateColumns: "max-content auto",
      columnGap: "1em",
      ...style,
    }}
  >
    ${entryEls}
  </div>`;
};
