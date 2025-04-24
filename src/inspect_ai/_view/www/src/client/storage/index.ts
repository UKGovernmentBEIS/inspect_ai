import JSON5 from "json5";
import { PersistedState } from "../../state/store";
import { getVscodeApi } from "../../utils/vscode";
import { ClientStorage } from "../api/types";

const resolveStorage = (): ClientStorage | undefined => {
  const vscodeApi = getVscodeApi();
  if (vscodeApi) {
    return {
      getItem: (_name: string) => {
        const state = vscodeApi.getState() as string;
        const deserialized = JSON5.parse(state) as {
          state: PersistedState;
          version: number;
        };
        return deserialized;
      },
      setItem: (_name: string, value: unknown) => {
        // TODO: This is pretty gnarly type hijinks
        const valObj = value as { state: PersistedState; version: number };
        const serialized = JSON5.stringify(valObj);
        vscodeApi.setState(serialized);
      },
      removeItem: (_name: string) => {
        vscodeApi.setState(null);
      },
    };
  }
  return undefined;
};

export default resolveStorage();
