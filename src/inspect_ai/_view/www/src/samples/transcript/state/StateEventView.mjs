// @ts-check
import { html } from "htm/preact";

import { EventPanel } from "../EventPanel.mjs";
import { RenderableChangeTypes } from "./StateEventRenderers.mjs";
import { StateDiffView } from "./StateDiffView.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../../types/log").StateEvent } props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StateEventView = ({ id, event, style }) => {
  const summary = summarizeChanges(event.changes);

  // Synthesize objects for comparison
  const [before, after] = synthesizeComparable(event.changes);

  const tabs = [
    html`<${StateDiffView}
      before=${before}
      after=${after}
      name="Diff"
      style=${{ margin: "1em 0em" }}
    />`,
  ];
  // This clone is important since the state is used by preact as potential values that are rendered
  // and as a result may be decorated with additional properties, etc..., resulting in DOM elements
  // appearing attached to state.
  const changePreview = generatePreview(event.changes, structuredClone(after));
  if (changePreview) {
    tabs.unshift(
      html`<div name="Summary" style=${{ margin: "1em 0em", width: "100%" }}>
        ${changePreview}
      </div>`,
    );
  }

  // Compute the title
  const title = event.event === "state" ? "State Updated" : "Store Updated";

  return html`
  <${EventPanel} id=${id} title="${title}" text=${tabs.length === 1 ? summary : undefined} collapse=${changePreview === undefined ? true : undefined} style=${style}>
    ${tabs}
  </${EventPanel}>`;
};

/**
 * Renders the value of a change based on its type.
 *
 * @param {import("../../../types/log").JsonChange[]} changes - The change object containing the value.
 * @param {Object} resolvedState - The change object containing the value.
 * @returns {import("preact").JSX.Element|Object|string|undefined} - The rendered HTML template if the value is an object with content and source, otherwise the value itself.
 */
const generatePreview = (changes, resolvedState) => {
  const results = [];
  for (const changeType of RenderableChangeTypes) {
    // Note that we currently only have renderers that depend upon
    // add, remove, replace, but we should likely add
    // move, copy, test
    const requiredMatchCount =
      changeType.signature.remove.length +
      changeType.signature.replace.length +
      changeType.signature.add.length;
    let matchingOps = 0;
    for (const change of changes) {
      if (
        changeType.signature[change.op] &&
        changeType.signature[change.op].length > 0
      ) {
        changeType.signature[change.op].forEach((signature) => {
          if (change.path.match(signature)) {
            matchingOps++;
          }
        });
      }
    }
    if (matchingOps === requiredMatchCount) {
      results.push(changeType.render(changes, resolvedState));
      // Only one renderer can process a change
      // TODO: consider changing this to allow many handlers to render (though then we sort of need
      // to match the renderer to the key (e.g. a rendered for `tool_choice` a renderer for `tools` etc..))
      break;
    }
  }
  return results.length > 0 ? results : undefined;
};

/**
 * Renders the value of a change based on its type.
 *
 * @param {import("../../../types/log").JsonChange[]} changes - The change object containing the value.
 * @returns {string} - A string summarizing the changes
 */
const summarizeChanges = (changes) => {
  const changeMap = {
    add: [],
    copy: [],
    move: [],
    replace: [],
    remove: [],
    test: [],
  };
  for (const change of changes) {
    changeMap[change.op].push(change.path);
  }

  const changeList = [];
  const totalOpCount = Object.keys(changeMap).reduce((prev, current) => {
    return prev + changeMap[current].length;
  }, 0);

  if (totalOpCount > 2) {
    Object.keys(changeMap).forEach((key) => {
      const opChanges = changeMap[key];
      if (opChanges.length > 0) {
        changeList.push(`${key} ${opChanges.length}`);
      }
    });
  } else {
    Object.keys(changeMap).forEach((key) => {
      const opChanges = changeMap[key];
      if (opChanges.length > 0) {
        changeList.push(`${key} ${opChanges.join(", ")}`);
      }
    });
  }
  return changeList.join(", ");
};

/**
 * Renders a view displaying a list of state changes.
 *
 * @param {import("../../../types/log").Changes} changes - The list of changes to be displayed.
 * @returns {[Object, Object]} The before and after objects
 */
const synthesizeComparable = (changes) => {
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
        setPath(before, change.from, change.value);
        setPath(after, change.path, change.value);
        break;
      case "remove":
        setPath(before, change.path, change.value);
        break;
      case "replace":
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
 *
 * @param {Object} target - The object into which to set the path
 * @param {string} path - The path of the value to set
 * @param {unknown} value - The value to set
 * @returns {Object} The mutated object
 */
function setPath(target, path, value) {
  const keys = parsePath(path);
  let current = target;

  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    if (!(key in current)) {
      // If the next key is a number, create an array, otherwise an object
      current[key] = isArrayIndex(keys[i + 1]) ? [] : {};
    }
    current = current[key];
  }

  const lastKey = keys[keys.length - 1];
  current[lastKey] = value;
}

/**
 * Places structure in an object (without placing values)
 *
 * @param {Object} target - The object into which to initialize the path
 * @param {string} path - The path of the value to set
 * @returns {Object} The mutated object
 */
function initializeArrays(target, path) {
  const keys = parsePath(path);
  let current = target;

  for (let i = 0; i < keys.length - 1; i++) {
    const key = keys[i];
    const nextKey = keys[i + 1];

    if (isArrayIndex(nextKey)) {
      current[key] = initializeArray(current[key], nextKey);
    } else {
      current[key] = initializeObject(current[key]);
    }

    current = current[key];
  }

  const lastKey = keys[keys.length - 1];
  if (isArrayIndex(lastKey)) {
    initializeArray(current, lastKey);
  }
}

/**
 * Parses a path into an array of keys
 *
 * @param {string} path - The path to split
 * @returns {string[]} Array of keys
 */
function parsePath(path) {
  return path.split("/").filter(Boolean);
}

/**
 * Checks if a key represents an array index
 *
 * @param {string} key - The key to check
 * @returns {boolean} True if the key is a number
 */
function isArrayIndex(key) {
  return /^\d+$/.test(key);
}

/**
 * Initializes an array at a given key, ensuring it is large enough
 *
 * @param {Array|undefined} current - The current array or undefined
 * @param {string} nextKey - The key of the next array index
 * @returns {Array} Initialized array
 */
function initializeArray(current, nextKey) {
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
 *
 * @param {Object|undefined} current - The current object or undefined
 * @returns {Object} Initialized object
 */
function initializeObject(current) {
  return current ?? {};
}
