// @ts-check
import { html } from "htm/preact";

import { EventPanel } from "../EventPanel.mjs";
import { RenderableChangeTypes } from "./StateEventRenderers.mjs";
import { StateDiffView } from "./StateDiffView.mjs";
import { ApplicationIcons } from "../../../appearance/Icons.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../../types/log").StateEvent } props.event - The event object to display.
 * @param {import("../TranscriptState.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StateEventView = ({ id, event, depth, stateManager }) => {
  const startingState = stateManager.getState();
  const resolvedState = stateManager.applyChanges(event.changes);

  const summary = summarizeChanges(event.changes);

  const tabs = [
    html`<${StateDiffView}
      starting=${startingState}
      ending=${resolvedState}
      name="Diff"
      style=${{ margin: "1em 0" }}
    />`,
  ];
  const changePreview = generatePreview(event.changes, resolvedState);
  if (changePreview) {
    tabs.unshift(
      html`<div name="Summary" style=${{ margin: "1em 0" }}>
        ${changePreview}
      </div>`,
    );
  }

  // Compute the title
  const title = event.event === "state" ? "State Updated" : "Store Updated";

  return html`
  <${EventPanel} id=${id} title="${title}" icon=${ApplicationIcons.metadata} text=${tabs.length === 1 ? summary : undefined} depth=${depth} collapse=${changePreview === undefined ? true : undefined}>
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
  for (const changeType of RenderableChangeTypes) {
    const requiredMatchCount =
      changeType.signature.remove.length +
      changeType.signature.replace.length +
      changeType.signature.add.length;
    let matchingOps = 0;
    for (const change of changes) {
      if (
        changeType.signature.remove.includes(change.path) ||
        changeType.signature.replace.includes(change.path) ||
        changeType.signature.add.includes(change.path)
      ) {
        matchingOps++;
      }
      if (matchingOps === requiredMatchCount) {
        return changeType.render(resolvedState);
      }
    }
  }
  return undefined;
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
