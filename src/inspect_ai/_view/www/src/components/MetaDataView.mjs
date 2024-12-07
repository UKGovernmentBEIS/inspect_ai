// @ts-check
import { html } from "htm/preact";
import { RenderedContent } from "./RenderedContent/RenderedContent.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

/**
 * Renders the MetaDataView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the table element.
 * @param {string} [props.baseClass] - The base class name for styling.
 * @param {string} [props.classes] - Additional class names for the table element.
 * @param {Object} [props.style] - Inline styles for the table element.
 * @param {Object[]|Record<string, string>} props.entries - The metadata entries to display.
 * @param {string} [props.tableOptions] - Options for table styling.
 * @param {boolean} [props.compact] - Whether to render the table in compact mode.
 * @returns {import("preact").JSX.Element} The component.
 */
export const MetaDataView = ({
  id,
  baseClass,
  classes,
  style,
  entries,
  tableOptions,
  compact,
}) => {
  const baseId = baseClass || "metadataview";

  const cellStyle = compact
    ? { padding: "0em" }
    : { padding: "0.3em 0.3em 0.3em 0em" };
  const cellKeyStyle = compact
    ? {
        fontWeight: "400",
        paddingRight: "0.2em",
        whiteSpace: "nowrap",
      }
    : {
        fontWeight: "400",
        paddingRight: "1em",
        whiteSpace: "nowrap",
      };
  const cellValueStyle = {
    fontWeight: "300",
    whiteSpace: "pre-wrap",
    wordWrap: "anywhere",
    fontSize: FontSize.small,
  };
  const cellKeyTextStyle = {
    fontSize: FontSize.small,
  };

  // Configure options for
  tableOptions = tableOptions || "sm";
  const tblClz = (tableOptions || "").split(",").map((option) => {
    return `table-${option}`;
  });

  // entries can be either a Record<string, stringable>
  // or an array of record with name/value on way in
  // but coerce to array of records for order
  /** @type {Array | undefined } */
  let coercedEntries;
  if (entries) {
    if (Array.isArray(entries)) {
      coercedEntries = entries;
    } else {
      coercedEntries = Object.entries(entries || {}).map(([key, value]) => {
        return { name: key, value };
      });
    }
  }

  const entryEls = (coercedEntries || []).map((entry, index) => {
    const id = `${baseId}-value-${index}`;
    return html`<tr class="${baseId}-row">
      <td
        class="${baseId}-key"
        style=${{ ...cellStyle, ...cellKeyStyle, ...cellKeyTextStyle }}
      >
        ${entry.name}
      </td>
      <td class="${baseId}-value" style=${{ ...cellStyle, ...cellValueStyle }}>
        <${RenderedContent} id=${id} entry=${entry} />
      </td>
    </tr>`;
  });

  return html`<table
    ...${{ id }}
    class="${classes || ""} table ${tblClz.join(" ")}"
    style=${{
      paddingLeft: "0",
      marginLeft: "0",
      marginBottom: "0.2rem",
      ...style,
    }}
  >
    <thead>
      <tr>
        <th colspan="2" style="${{ padding: 0 }}"></th>
      </tr>
    </thead>
    <tbody>
      ${entryEls}
    </tbody>
  </table>`;
};
