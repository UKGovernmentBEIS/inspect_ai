import { applyOperation } from "fast-json-patch";
/**
 * @typedef {Object} StateManager
 * @property {function(): Object} getState - Retrieves the current state object.
 * @property {function(Object): void} setState - Updates the current state with a new state object.
 * @property {function(import("../../types/log").Changes): Object} applyChanges - Updates the current state with a new state object.*
 */

/**
 * Manages the state, providing methods to retrieve and update it.
 *
 * @returns {StateManager} An object containing `getState` and `onState` methods for managing state.
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
    setState: (newState) => {
      state = structuredClone(newState);
    },
    /**
     * Updates the current state with a new state object.
     *
     * @param {import("../../types/log").Changes} changes - The new state object to update with.
     */
    applyChanges: (changes) => {
      state = structuredClone(state);
      changes.forEach((change) => {
        //@ts-ignore
        applyOperation(state, change);
      });
      return state;
    },
  };
};
