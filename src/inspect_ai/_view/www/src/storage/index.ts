import { ClientStorage } from "../api/types";
import { PersistedState } from "../state/store";
import { getVscodeApi } from "../utils/vscode";

const resolveStorage = (): ClientStorage | undefined => {
  const vscodeApi = getVscodeApi();
  if (vscodeApi) {
    return {
      getItem: (_name: string) => {
        const state = vscodeApi.getState() as PersistedState;
        return state;
      },
      setItem: (_name: string, value: unknown) => {
        // TODO: This is pretty gnarly type hijinks
        const valObj = value as { state: PersistedState; version: number };
        vscodeApi.setState(valObj);
      },
      removeItem: (_name: string) => {
        vscodeApi.setState(null);
      },
    };
  }
  return undefined;
};

export default resolveStorage();
