import clsx from "clsx";
import {
  FC,
  KeyboardEvent,
  RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { Virtuoso, VirtuosoHandle } from "react-virtuoso";
import { RenderedContent } from "./RenderedContent";

import { useCollapsibleIds } from "../../state/hooks";
import { useVirtuosoState } from "../../state/scrolling";
import { useStore } from "../../state/store";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./RecordTree.module.css";
import { resolveStoreKeys } from "./record_processors/store";
import { RecordProcessor } from "./record_processors/types";

const kRecordTreeKey = "record-tree-key";

interface RecordTreeProps {
  id: string;
  record: Record<string, unknown>;
  className?: string | string[];
  scrollRef?: RefObject<HTMLDivElement | null>;
  defaultExpandLevel?: number;
  processStore?: boolean;
}

/**
 * Renders the MetaDataView component.
 */
export const RecordTree: FC<RecordTreeProps> = ({
  id,
  record,
  className,
  scrollRef,
  defaultExpandLevel = 1,
  processStore = false,
}) => {
  // The virtual list handle and state
  const listHandle = useRef<VirtuosoHandle | null>(null);
  const { getRestoreState } = useVirtuosoState(
    listHandle,
    `metadata-grid-${id}`,
  );

  // Collapse state
  const [collapsedIds, setCollapsed, clearIds] = useCollapsibleIds(id);
  const setCollapsedIds = useStore(
    (state) => state.sampleActions.setCollapsedIds,
  );

  // Clear the collapsed ids when the component unmounts
  useEffect(() => {
    return () => {
      clearIds();
    };
  }, [clearIds, id]);

  // Tree-ify the record (creates a flat lsit of items with depth property)
  const items = useMemo(() => {
    return toTreeItems(
      record,
      collapsedIds || {},
      processStore ? [resolveStoreKeys] : [],
    );
  }, [record, collapsedIds, processStore]);

  // If collapsedIds is not set, we need to set it to the default state
  useEffect(() => {
    if (collapsedIds) {
      return;
    }

    const defaultCollapsedIds = items.reduce((prev, item) => {
      if (item.depth >= defaultExpandLevel && item.hasChildren) {
        return {
          ...prev,
          [item.id]: true,
        };
      }
      return prev;
    }, {});
    setCollapsedIds(id, defaultCollapsedIds);
  }, [collapsedIds, items]);

  // Keyboard handling for tree
  const keyUpHandler = useCallback(
    (itemId: string, index: number) => {
      return (event: KeyboardEvent) => {
        switch (event.key) {
          case "Enter":
            event.preventDefault();
            event.stopPropagation();
            setCollapsed(itemId, !collapsedIds?.[id]);
            break;
          case "ArrowDown": {
            event.preventDefault();
            event.stopPropagation();
            // focus next
            if (index === items.length - 1) {
              return;
            }
            const treeRoot = document.getElementById(id);
            const nextEl = treeRoot?.querySelector(
              `.${kRecordTreeKey}[data-index="${index + 1}"]`,
            );
            if (nextEl) {
              (nextEl as HTMLElement).focus();
            }
            break;
          }
          case "ArrowUp": {
            event.preventDefault();
            event.stopPropagation();
            // focus previous
            if (index === 0) {
              return;
            }
            const treeRoot = document.getElementById(id);
            const prevEl = treeRoot?.querySelector(
              `.${kRecordTreeKey}[data-index="${index - 1}"]`,
            );
            if (prevEl) {
              (prevEl as HTMLElement).focus();
            }
            break;
          }
          case "ArrowRight":
            event.preventDefault();
            event.stopPropagation();
            setCollapsed(itemId, false);
            break;
          case "ArrowLeft":
            event.preventDefault();
            event.stopPropagation();
            setCollapsed(itemId, true);
            break;
        }
      };
    },
    [collapsedIds, items],
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
          data-index={index}
          className={clsx(
            kRecordTreeKey,
            styles.key,
            "font-monospace",
            "text-style-secondary",
          )}
          onKeyUp={keyUpHandler(item.id, index)}
          tabIndex={0}
          onClick={() => {
            setCollapsed(item.id, !collapsedIds?.[item.id]);
          }}
        >
          <div>
            {item.hasChildren ? (
              <pre className={clsx(styles.pre)}>
                <i
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
              renderOptions={{ renderString: "pre" }}
            />
          ) : undefined}
        </div>
      </div>
    );
  };

  if (!scrollRef) {
    // No virtualization - render directly
    return (
      <div
        id={id}
        className={clsx(className, "samples-list")}
        style={{ width: "100%" }}
        tabIndex={0}
      >
        {items.map((_, index) => renderRow(index))}
      </div>
    );
  }
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
  recordProcessors: RecordProcessor[] = [],
  currentDepth = 0,
  currentPath: string[] = [],
): MetadataItem[] => {
  if (!record) {
    return [];
  }

  // Apply any record processors
  if (recordProcessors.length > 0) {
    for (const processor of recordProcessors) {
      record = processor(record);
    }
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
