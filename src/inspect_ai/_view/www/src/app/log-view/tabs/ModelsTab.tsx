import { FC, useMemo } from "react";
import { EvalSpec, EvalStats, Status } from "../../../@types/log";
import { kLogViewModelsTabId } from "../../../constants";
import { ModelCard } from "../../plan/ModelCard";
import { UsageCard } from "../../usage/UsageCard";

// Individual hook for Info tab
export const useModelsTab = (
  evalSpec: EvalSpec | undefined,
  evalStats: EvalStats | undefined,
  evalStatus?: Status,
) => {
  return useMemo(() => {
    return {
      id: kLogViewModelsTabId,
      label: "Models",
      scrollable: true,
      component: ModelTab,
      componentProps: {
        evalSpec,
        evalStats,
        evalStatus,
      },
    };
  }, [evalSpec, evalStats]);
};

interface ModelTabProps {
  evalSpec?: EvalSpec;
  evalStats?: EvalStats;
  evalStatus?: Status;
}

export const ModelTab: FC<ModelTabProps> = ({
  evalSpec,
  evalStats,
  evalStatus,
}) => {
  return (
    <div style={{ width: "100%" }}>
      <div style={{ padding: "0.5em 1em 0 1em", width: "100%" }}>
        {evalSpec ? <ModelCard evalSpec={evalSpec} /> : undefined}
        {evalStatus !== "started" &&
          evalStats?.model_usage &&
          Object.keys(evalStats.model_usage).length > 0 && (
            <UsageCard stats={evalStats} />
          )}
      </div>
    </div>
  );
};
