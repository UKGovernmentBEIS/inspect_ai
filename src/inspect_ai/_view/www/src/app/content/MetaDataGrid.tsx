import clsx from "clsx";
import { CSSProperties, FC, Fragment } from "react";
import styles from "./MetadataGrid.module.css";
import { RenderedContent } from "./RenderedContent";

interface MetadataGridProps {
  id?: string;
  className?: string | string[];
  style?: CSSProperties;
  size?: "mini" | "small";
  entries: Record<string, unknown>;
  plain?: boolean;
}

/**
 * Renders the MetaDataView component.
 */
export const MetaDataGrid: FC<MetadataGridProps> = ({
  id,
  entries,
  className,
  size,
  style,
  plain,
}) => {
  const baseId = "metadata-grid";
  const fontStyle =
    size === "mini" ? "text-size-smallest" : "text-size-smaller";

  const entryEls = entryRecords(entries).map((entry, index) => {
    const id = `${baseId}-value-${index}`;
    return (
      <Fragment key={`${baseId}-record-${index}`}>
        {index !== 0 ? (
          <div
            style={{
              gridColumn: "1 / -1",
              borderBottom: `${!plain ? "solid 1px var(--bs-light-border-subtle" : ""}`,
            }}
          ></div>
        ) : undefined}
        <div
          className={clsx(
            `${baseId}-key`,
            styles.cell,
            "text-style-label",
            "text-style-secondary",
            fontStyle,
          )}
        >
          {entry?.name}
        </div>
        <div className={clsx(styles.value, `${baseId}-value`, fontStyle)}>
          {entry && (
            <RenderedContent
              id={id}
              entry={entry}
              renderObject={(obj: any) => {
                return (
                  <MetaDataGrid
                    id={id}
                    className={clsx(styles.nested)}
                    entries={obj}
                    size={size}
                    plain={plain}
                  />
                );
              }}
            />
          )}
        </div>
      </Fragment>
    );
  });

  return (
    <div id={id} className={clsx(className, styles.grid)} style={style}>
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
  entries: { name: string; value: unknown }[] | Record<string, unknown>,
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
