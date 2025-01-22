import clsx from "clsx";
import React from "preact/compat";
import styles from "./MetadataGrid.module.css";
import { RenderedContent } from "./RenderedContent/RenderedContent";

interface MetadataGridProps {
  id: string;
  classes?: string;
  style?: React.CSSProperties;
  entries: Record<string, string>;
  plain?: boolean;
}

/**
 * Renders the MetaDataView component.
 */
export const MetaDataGrid: React.FC<MetadataGridProps> = ({
  id,
  entries,
  classes,
  style,
  plain,
}) => {
  const baseId = "metadata-grid";

  const entryEls = entryRecords(entries).map((entry, index) => {
    const id = `${baseId}-value-${index}`;
    return (
      <React.Fragment>
        <div
          style={{
            gridColumn: "1 / -1",
            borderBottom: `${!plain ? "solid 1px var(--bs-light-border-subtle" : ""}`,
          }}
        ></div>
        <div
          className={clsx(
            `${baseId}-key`,
            styles.cell,
            "text-style-label",
            "text-style-secondary",
            "text-size-small",
          )}
        >
          {entry.name}
        </div>
        <div
          className={clsx(styles.value, `${baseId}-value`, "text-size-small")}
        >
          <RenderedContent id={id} entry={entry} />
        </div>
      </React.Fragment>
    );
  });

  return (
    <div id={id} className={clsx(classes, styles.grid)} style={style}>
      {entryEls}
    </div>
  );
};

// entries can be either a Record<string, stringable>
// or an array of record with name/value on way in
// but coerce to array of records for order
/**
 * Ensure the proper type for entries
 */
const entryRecords = (
  entries: { name: string; value: unknown }[] | Record<string, string>,
): { name: string; value: unknown }[] => {
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
