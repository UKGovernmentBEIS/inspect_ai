/**
 * @typedef {Object} StateManager
 * @property {string} scope - The scope (name) of this statemanager
 * @property {function(): Object} getState - Retrieves the current state object.
 * @property {function(Object): void} initializeState - Initializes the current state with a new state object.
 * @property {function(import("../../types/log").Changes): Object} applyChanges - Updates the current state with a new state object.*
 */

/**
 * Class representing a node for an event in a tree.
 */
export class EventNode {
  /**
   * Create an EventNode.
   * @param { import("../../types/log").SampleInitEvent | import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent | import("../../types/log").ToolEvent | import("../../types/log").InputEvent | import("../../types/log").ErrorEvent | import("../../types/log").ApprovalEvent } event - This event.
   * @param {number} depth - the depth of this item
   */
  constructor(event, depth) {
    /**
     * @type { import("../../types/log").SampleInitEvent | import("../../types/log").StateEvent | import("../../types/log").StoreEvent | import("../../types/log").ModelEvent | import("../../types/log").LoggerEvent | import("../../types/log").InfoEvent | import("../../types/log").StepEvent | import("../../types/log").SubtaskEvent| import("../../types/log").ScoreEvent | import("../../types/log").ToolEvent | import("../../types/log").InputEvent | import("../../types/log").ErrorEvent | import("../../types/log").ApprovalEvent } event - This event.
     */
    this.event = event;

    /**
     * @type {EventNode[]} children - An array of child EventNodes.
     */
    this.children = [];

    /**
     * @type {number} depth - the depth of this item
     */
    this.depth = depth;
  }
}
