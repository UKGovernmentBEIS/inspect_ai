import clsx from "clsx";
import styles from "./MetaDataView.module.css";
import { RenderedContent } from "./RenderedContent";

interface MetadataViewProps {
  id?: string;
  style?: React.CSSProperties;
  entries: Record<string, unknown>;
  tableOptions?: string;
  compact?: boolean;
  className?: string | string[];
}

/**
 * Renders the MetaDataView component.
 */
export const MetaDataView: React.FC<MetadataViewProps> = ({
  id,
  style,
  entries,
  tableOptions,
  compact,
  className,
}) => {
  const baseId = "metadataview";

  // Configure options for
  tableOptions = tableOptions || "sm";
  const tblClz = (tableOptions || "").split(",").map((option) => {
    return `table-${option}`;
  });

  const coercedEntries = toNameValues(entries);

  const entryEls = (coercedEntries || []).map((entry, index) => {
    const id = `${baseId}-value-${index}`;
    return (
      <tr key={id}>
        <td
          className={clsx(
            styles.cell,
            styles.cellKey,
            "text-size-small",
            "text-style-label",
          )}
        >
          {entry.name}
        </td>
        <td className={clsx(styles.cell, styles.cellValue, "text-size-small")}>
          <RenderedContent id={id} entry={entry} />
        </td>
      </tr>
    );
  });

  return (
    <table
      id={id}
      className={clsx(
        "table",
        tblClz,
        styles.table,
        compact ? styles.compact : undefined,
        className,
      )}
      style={style}
    >
      <thead>
        <tr>
          <th colSpan={2} className={"th"}></th>
        </tr>
      </thead>
      <tbody>{entryEls}</tbody>
    </table>
  );
};

// entries can be either a Record<string, stringable>
// or an array of record with name/value on way in
// but coerce to array of records for order
const toNameValues = (
  entries?: Array<{ name: string; value: unknown }> | Record<string, unknown>,
): Array<{ name: string; value: unknown }> | undefined => {
  if (entries) {
    if (Array.isArray(entries)) {
      return entries;
    } else {
      return Object.entries(entries || {}).map(([key, value]) => {
        return { name: key, value };
      });
    }
  } else {
    return entries;
  }
};
