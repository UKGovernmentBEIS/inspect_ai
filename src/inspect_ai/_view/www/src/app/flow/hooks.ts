import { useEffect } from "react";
import { useStore } from "../../state/store";

export const useFlowServerData = (dir: string) => {
  const api = useStore((state) => state.api);
  const flowDir = useStore((state) => state.logs.flowDir);
  const updateFlowData = useStore((state) => state.logsActions.updateFlowData);

  useEffect(() => {
    const fetchFlow = async () => {
      const flowStr = await api?.get_flow(dir);

      // Set the flow data into state
      updateFlowData(dir, flowStr);
    };
    if (dir !== flowDir) {
      fetchFlow();
    }
  }, [dir, flowDir, api, updateFlowData]);
};
