import { b as reactExports } from "./vendor-grid.js";
import { u as useStore } from "./index.js";
const useFlowServerData = (dir) => {
  const api = useStore((state) => state.api);
  const flowDir = useStore((state) => state.logs.flowDir);
  const updateFlowData = useStore((state) => state.logsActions.updateFlowData);
  reactExports.useEffect(() => {
    const fetchFlow = async () => {
      const flowStr = await api?.get_flow(dir);
      updateFlowData(dir, flowStr);
    };
    if (dir !== flowDir) {
      fetchFlow();
    }
  }, [dir, flowDir, api, updateFlowData]);
};
export {
  useFlowServerData as u
};
//# sourceMappingURL=hooks.js.map
