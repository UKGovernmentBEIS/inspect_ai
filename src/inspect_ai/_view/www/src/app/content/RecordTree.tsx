import clsx from "clsx";
import { FC, RefObject, useEffect, useMemo, useRef } from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { useVirtuosoState } from "../../state/scrolling";
import { RenderedContent } from "./RenderedContent";

import { useCollapsibleIds } from "../../state/hooks";
import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./RecordTree.module.css";

interface RecordTreeProps {
  id: string;
  record: Record<string, unknown>;
  className?: string | string[];
  scrollRef?: RefObject<HTMLDivElement | null>;
}

/**
 * Renders the MetaDataView component.
 */
export const RecordTree: FC<RecordTreeProps> = ({
  id,
  record,
  className,
  scrollRef,
}) => {
  const [collapsedIds, setCollapsed] = useCollapsibleIds(id);
  const setCollapsedIds = useStore(
    (state) => state.sampleActions.setCollapsedIds,
  );

  const items = useMemo(() => {
    return toTreeItems(record, collapsedIds || {});
  }, [record, collapsedIds]);

  useEffect(() => {
    if (collapsedIds) {
      return;
    }

    const defaultCollapsedIds = items.reduce((prev, item) => {
      if (item.hasChildren) {
        return {
          ...prev,
          [item.id]: true,
        };
      }
      return prev;
    }, {});
    setCollapsedIds(id, defaultCollapsedIds);
  }, [collapsedIds, items]);

  const listHandle = useRef<VirtuosoHandle | null>(null);

  const { getRestoreState } = useVirtuosoState(
    listHandle,
    `metadata-grid-${id}`,
  );

  const renderRow = (index: number) => {
    const item = items[index];

    return (
      <div
        key={item.id}
        className={clsx(styles.keyPairContainer, "text-size-small")}
        style={{
          paddingLeft: `${item.depth * 20}px`,
        }}
      >
        <div
          className={clsx(styles.key, "font-monospace", "text-style-secondary")}
        >
          <div>
            {item.hasChildren ? (
              <pre className={clsx(styles.pre)}>
                <i
                  onClick={() => {
                    setCollapsed(item.id, !collapsedIds?.[item.id]);
                  }}
                  className={clsx(
                    collapsedIds && collapsedIds[item.id]
                      ? ApplicationIcons.tree.closed
                      : ApplicationIcons.tree.open,
                    styles.treeIcon,
                  )}
                />
              </pre>
            ) : undefined}
          </div>
          <pre className={clsx(styles.pre)}>{item.key}:</pre>
        </div>
        <div>
          {item.value !== null &&
          (!item.hasChildren || collapsedIds?.[item.id]) ? (
            <RenderedContent
              id={`${id}-value-${item.id}`}
              entry={{
                name: item.key,
                value: item.value,
              }}
            />
          ) : undefined}
        </div>
      </div>
    );
  };

  return (
    <Virtuoso
      ref={listHandle}
      customScrollParent={scrollRef?.current ? scrollRef.current : undefined}
      id={id}
      style={{ width: "100%", height: "100%" }}
      data={items}
      defaultItemHeight={50}
      itemContent={renderRow}
      atBottomThreshold={30}
      increaseViewportBy={{ top: 300, bottom: 300 }}
      overscan={{
        main: 10,
        reverse: 10,
      }}
      className={clsx(className, "samples-list")}
      skipAnimationFrameInResizeObserver={true}
      restoreStateFrom={getRestoreState()}
      tabIndex={0}
    />
  );
};

interface MetadataItem {
  id: string;
  key: string;
  value: string | number | boolean | null;
  depth: number;
  hasChildren: boolean;
}

export const toTreeItems = (
  record: Record<string, unknown>,
  collapsedIds: Record<string, boolean>,
  currentDepth = 0,
  currentPath: string[] = [],
): MetadataItem[] => {
  if (!record) {
    return [];
  }

  const result: MetadataItem[] = [];

  Object.entries(record).forEach(([key, value], index) => {
    const itemSegment = index.toString();
    result.push(
      ...processNodeRecursive(
        key,
        value,
        currentDepth,
        currentPath,
        itemSegment,
        collapsedIds,
      ),
    );
  });

  return result;
};

const processNodeRecursive = (
  key: string,
  value: unknown,
  depth: number,
  parentPath: string[],
  thisPath: string,
  collapsedIds: Record<string, boolean>,
): MetadataItem[] => {
  const items: MetadataItem[] = [];
  const currentItemPath = [...parentPath, thisPath];
  const id = `${depth}.${currentItemPath.join(".")}`;

  if (isPrimitiveOrNull(value)) {
    items.push({
      id,
      key,
      value: value === undefined ? null : value,
      depth,
      hasChildren: false,
    });
    return items;
  }

  // For non-primitives (objects, arrays, functions, etc.)
  let displayValue: string | number | boolean | null = null;
  let processChildren = false;

  if (Array.isArray(value)) {
    processChildren = true;
    displayValue = `Array(${value.length})`;
  } else if (typeof value === "object" && value !== null) {
    processChildren = true;
    displayValue = `Object(${Object.keys(value).length})`;
  } else {
    // Other types like functions, symbols. These are treated as leaf nodes.
    displayValue = String(value);
    processChildren = false;
  }

  // Add the item
  items.push({ id, key, value: displayValue, depth, hasChildren: true });

  // Process children
  if (processChildren && !collapsedIds[id]) {
    const childDepth = depth + 1;
    if (Array.isArray(value)) {
      if (value.length > 0) {
        value.forEach((element, index) => {
          const elementKey = `[${index}]`;
          const elementIdentifier = `[${index}]`;
          items.push(
            ...processNodeRecursive(
              elementKey,
              element,
              childDepth,
              currentItemPath,
              elementIdentifier,
              collapsedIds,
            ),
          );
        });
      }
    } else if (typeof value === "object" && value !== null) {
      // Process object properties
      Object.entries(value as Record<string, unknown>).forEach(
        ([childKey, childValue], index) => {
          const childIdentifier = index.toString();
          items.push(
            ...processNodeRecursive(
              childKey,
              childValue,
              childDepth,
              currentItemPath,
              childIdentifier,
              collapsedIds,
            ),
          );
        },
      );
    }
  }

  return items;
};

const isPrimitiveOrNull = (
  value: unknown,
): value is string | number | boolean | null | undefined => {
  return (
    value === null ||
    value === undefined ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
};
