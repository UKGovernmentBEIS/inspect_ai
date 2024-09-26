import { applyPatch } from "fast-json-patch";

/**
 * Manages the state, providing methods to retrieve and update it.
 *
 * @param {string} scope - The name identifier for the state manager.
 * @returns {import("./Types.mjs").StateManager} An object containing `getState` and `onState` methods for managing state.
 */
export const initStateManager = (scope) => {
  /** @type {Object} */
  let state = {};
  return {
    scope: scope,

    /**
     * Retrieves the current state object.
     *
     * @returns {Object} The current state object.
     */
    getState: () => {
      return state;
    },
    /**
     * Updates the current state with a new state object.
     *
     * @param {Object} newState - The new state object to update with.
     */
    initializeState: (newState) => {
      state = newState;
    },
    /**
     * Updates the current state with a new state object.
     *
     * @param {import("../../types/log").Changes} changes - The new state object to update with.
     */
    applyChanges: (changes) => {
      try {
        state = applyPatch(
          structuredClone(state),
          structuredClone(changes).map(ensureValidChange),
          true,
        ).newDocument;
      } catch (ex) {
        const ops = changes.reduce((prev, change) => {
          if (!Object.keys(prev).includes(change.op)) {
            prev[change.op] = [];
          }
          prev[change.op].push(change.path);
          return prev;
        }, {});
        const message = `${ex.name}\nFailed to apply patch:\n${JSON.stringify(ops, undefined, 2)}`;
        console.error(message);
      }
    },
  };
};

/**
 * Ensures that the change is valid (provides default values)
 * If the operation is "add" and `value` is not present, it assigns `null` to `value`.
 *
 * @param { import("../../types/log").JsonChange } change - The change object containing the operation and value.
 * @returns {Object} The modified change object with a guaranteed `value` property.
 */
const ensureValidChange = (change) => {
  if (change.op === "add" && !change.value) {
    change.value = null;
  }
  return change;
};
