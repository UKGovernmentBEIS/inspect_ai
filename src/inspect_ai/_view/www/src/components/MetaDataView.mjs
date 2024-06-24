import { html } from "htm/preact";
import { RenderedContent } from "./RenderedContent.mjs";

export const MetaDataView = ({
  id,
  baseClass,
  classes,
  style,
  entries,
  tableOptions,
  context,
  expanded,
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
    fontSize: "0.8rem",
  };
  const cellKeyTextStyle = {
    fontSize: "0.8rem",
  };

  // Configure options for
  tableOptions = tableOptions || "sm";
  const tblClz = (tableOptions || "").split(",").map((option) => {
    return `table-${option}`;
  });

  // entries can be either a Record<string, stringable>
  // or an array of record with name/value on way in
  // but coerce to array of records for order
  if (entries && !Array.isArray(entries)) {
    entries = Object.entries(entries || {}).map(([key, value]) => {
      return { name: key, value };
    });
  }

  const entryEls = (entries || []).map((entry, index) => {
    const id = `${baseId}-value-${index}`;
    return html`<tr class="${baseId}-row">
      <td
        class="${baseId}-key"
        style=${{ ...cellStyle, ...cellKeyStyle, ...cellKeyTextStyle }}
      >
        ${entry.name}
      </td>
      <td class="${baseId}-value" style=${{ ...cellStyle, ...cellValueStyle }}>
        <${RenderedContent}
          id=${id}
          entry=${entry}
          context=${context}
          options=${{ expanded }}
        />
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
