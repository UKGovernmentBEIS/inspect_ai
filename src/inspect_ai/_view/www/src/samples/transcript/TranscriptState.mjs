import { applyPatch } from "fast-json-patch";

/**
 * Manages the state, providing methods to retrieve and update it.
 *
 * @returns {import("./Types.mjs").StateManager} An object containing `getState` and `onState` methods for managing state.
 */
export const initStateManager = () => {
  /** @type {Object} */
  let state = {};
  return {
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
      state = applyPatch(
        structuredClone(state),
        structuredClone(changes).map(ensureValidChange),
        true,
      ).newDocument;
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
