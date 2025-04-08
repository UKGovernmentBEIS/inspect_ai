// @ts-check

import clsx from "clsx";
import {
  Changes,
  JsonChange,
  Op,
  StateEvent,
  StoreEvent,
} from "../../../../@types/log";
import { formatDateTime } from "../../../../utils/format";
import { EventPanel } from "../event/EventPanel";
import { StateDiffView } from "./StateDiffView";
import {
  RenderableChangeTypes,
  StoreSpecificRenderableTypes,
} from "./StateEventRenderers";

import { FC, useMemo } from "react";
import styles from "./StateEventView.module.css";

interface StateEventViewProps {
  id: string;
  event: StateEvent | StoreEvent;
  isStore?: boolean;
  className?: string | string[];
}

/**
 * Renders the StateEventView component.
 */
export const StateEventView: FC<StateEventViewProps> = ({
  id,
  event,
  isStore = false,
  className,
}) => {
  const summary = useMemo(() => {
    return summarizeChanges(event.changes);
  }, [event.changes]);

  // Synthesize objects for comparison
  const [before, after] = useMemo(() => {
    try {
      return synthesizeComparable(event.changes);
    } catch (e) {
      console.error(
        "Unable to synthesize comparable object to display state diffs.",
        e,
      );
      return [{}, {}];
    }
  }, [event.changes]);

  // This clone is important since the state is used by react as potential values that are rendered
  // and as a result may be decorated with additional properties, etc..., resulting in DOM elements
  // appearing attached to state.
  const changePreview = useMemo(() => {
    return generatePreview(event.changes, structuredClone(after), isStore);
  }, [event.changes, after, isStore]);
  // Compute the title
  const title = event.event === "state" ? "State Updated" : "Store Updated";

  return (
    <EventPanel
      id={id}
      title={title}
      className={className}
      subTitle={formatDateTime(new Date(event.timestamp))}
      text={!changePreview ? summary : undefined}
      collapse={changePreview === undefined ? true : undefined}
    >
      {changePreview ? (
        <div data-name="Summary" className={clsx(styles.summary)}>
          {changePreview}
        </div>
      ) : undefined}
      <StateDiffView
        before={before}
        after={after}
        data-name="Diff"
        className={clsx(styles.diff)}
      />
    </EventPanel>
  );
};

/**
 * Renders the value of a change based on its type.
 */
const generatePreview = (
  changes: JsonChange[],
  resolvedState: Record<string, unknown>,
  isStore: boolean,
) => {
  const results = [];
  for (const changeType of [
    ...RenderableChangeTypes,
    ...(isStore ? StoreSpecificRenderableTypes : []),
  ]) {
    if (changeType.signature) {
      // Note that we currently only have renderers that depend upon
      // add, remove, replace, but we should likely add
      // move, copy, test
      const requiredMatchCount =
        changeType.signature.remove.length +
        changeType.signature.replace.length +
        changeType.signature.add.length;
      let matchingOps = 0;
      for (const change of changes) {
        const op = change.op;
        switch (op) {
          case "add":
            if (
              changeType.signature.add &&
              changeType.signature.add.length > 0
            ) {
              changeType.signature.add.forEach((signature) => {
                if (change.path.match(signature)) {
                  matchingOps++;
                }
              });
            }
            break;
          case "remove":
            if (
              changeType.signature.remove &&
              changeType.signature.remove.length > 0
            ) {
              changeType.signature.remove.forEach((signature) => {
                if (change.path.match(signature)) {
                  matchingOps++;
                }
              });
            }
            break;
          case "replace":
            if (
              changeType.signature.replace &&
              changeType.signature.replace.length > 0
            ) {
              changeType.signature.replace.forEach((signature) => {
                if (change.path.match(signature)) {
                  matchingOps++;
                }
              });
            }
            break;
        }
      }
      if (matchingOps === requiredMatchCount) {
        const el = changeType.render(changes, resolvedState);
        results.push(el);
        // Only one renderer can process a change
        // TODO: consider changing this to allow many handlers to render (though then we sort of need
        // to match the renderer to the key (e.g. a rendered for `tool_choice` a renderer for `tools` etc..))
        break;
      }
    } else if (changeType.match) {
      const matches = changeType.match(changes);
      if (matches) {
        const el = changeType.render(changes, resolvedState);
        results.push(el);
        break;
      }
    }
  }
  return results.length > 0 ? results : undefined;
};

/**
 * Renders the value of a change based on its type.
 */
const summarizeChanges = (changes: JsonChange[]): string => {
  const changeMap: Record<Op, string[]> = {
    add: [],
    copy: [],
    move: [],
    replace: [],
    remove: [],
    test: [],
  };
  for (const change of changes) {
    switch (change.op) {
      case "add":
        changeMap.add.push(change.path);
        break;
      case "copy":
        changeMap.copy.push(change.path);
        break;
      case "move":
        changeMap.move.push(change.path);
        break;
      case "replace":
        changeMap.replace.push(change.path);
        break;
      case "remove":
        changeMap.remove.push(change.path);
        break;
      case "test":
        changeMap.test.push(change.path);
        break;
    }
  }

  const changeList: string[] = [];
  const totalOpCount = Object.keys(changeMap).reduce((prev, current) => {
    return prev + changeMap[current as Op].length;
  }, 0);

  if (totalOpCount > 2) {
    Object.keys(changeMap).forEach((key) => {
      const opChanges = changeMap[key as Op];
      if (opChanges.length > 0) {
        changeList.push(`${key} ${opChanges.length}`);
      }
    });
  } else {
    Object.keys(changeMap).forEach((key) => {
      const opChanges = changeMap[key as Op];
      if (opChanges.length > 0) {
        changeList.push(`${key} ${opChanges.join(", ")}`);
      }
    });
  }
  return changeList.join(", ");
};

/**
 * Renders a view displaying a list of state changes.
 */
const synthesizeComparable = (changes: Changes) => {
  const before = {};
  const after = {};

  for (const change of changes) {
    switch (change.op) {
      case "add":
        // 'Fill in' arrays with empty strings to ensure there is no unnecessary diff
        initializeArrays(before, change.path);
        initializeArrays(after, change.path);
        setPath(after, change.path, change.value);
        break;
      case "copy":
        setPath(before, change.path, change.value);
        setPath(after, change.path, change.value);
        break;
      case "move":
        setPath(before, change.from || "", change.value);
        setPath(after, change.path, change.value);
        break;
      case "remove":
        setPath(before, change.path, change.value);
        break;
      case "replace":
        // 'Fill in' arrays with empty strings to ensure there is no unnecessary diff
        initializeArrays(before, change.path);
        initializeArrays(after, change.path);

        setPath(before, change.path, change.replaced);
        setPath(after, change.path, change.value);
        break;
      case "test":
        break;
    }
  }
  return [before, after];
};

/**
 * Sets a value at a path in an object
 */
function setPath(
  target: Record<string, unknown>,
  path: string,
  value: unknown,
): void {
  const keys = parsePath(path);
  let current: Record<string, unknown> = target;

  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    if (!(key in current)) {
      // If the next key is a number, create an array, otherwise an object
      current[key] = isArrayIndex(keys[i + 1]) ? [] : {};
    }
    current = current[key] as Record<string, unknown>;
  }

  const lastKey = keys[keys.length - 1];
  current[lastKey] = value;
}

/**
 * Places structure in an object (without placing values)
 */
function initializeArrays(target: Record<string, unknown>, path: string): void {
  const keys = parsePath(path);
  let current: Record<string, unknown> = target;

  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    const nextKey = keys[i + 1];

    if (isArrayIndex(nextKey)) {
      current[key] = initializeArray(
        current[key] as string[] | undefined,
        nextKey,
      );
    } else {
      current[key] = initializeObject(current[key] as object | undefined);
    }

    current = current[key] as Record<string, unknown>;
  }

  const lastKey = keys[keys.length - 1];
  if (isArrayIndex(lastKey)) {
    const lastValue = current[lastKey] as string[] | undefined;
    initializeArray(lastValue, lastKey);
  }
}

/**
 * Parses a path into an array of keys
 */
function parsePath(path: string): string[] {
  return path.split("/").filter(Boolean);
}

/**
 * Checks if a key represents an array index
 */
function isArrayIndex(key: string): boolean {
  return /^\d+$/.test(key);
}

/**
 * Initializes an array at a given key, ensuring it is large enough
 */
function initializeArray(
  current: Array<string> | undefined,
  nextKey: string,
): Array<string> {
  if (!Array.isArray(current)) {
    current = [];
  }
  const nextKeyIndex = parseInt(nextKey, 10);
  while (current.length < nextKeyIndex) {
    current.push("");
  }
  return current;
}

/**
 * Initializes an object at a given key if it doesn't exist
 */
function initializeObject(current?: Object): Object {
  return current ?? {};
}
