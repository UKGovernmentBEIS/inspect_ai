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
 * @param {import("../Types.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StateEventView = ({ id, event, style, stateManager }) => {
  const startingState = stateManager.getState();
  stateManager.applyChanges(event.changes);
  const resolvedState = stateManager.getState();

  const summary = summarizeChanges(event.changes);

  const tabs = [
    html`<${StateDiffView}
      starting=${startingState}
      ending=${resolvedState}
      name="Diff"
      style=${{ margin: "1em 0em" }}
    />`,
  ];
  // This clone is important since the state is used by preact as potential values that are rendered
  // and as a result may be decorated with additional properties, etc..., resulting in DOM elements
  // appearing attached to state.
  const changePreview = generatePreview(
    event.changes,
    structuredClone(resolvedState),
  );
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
