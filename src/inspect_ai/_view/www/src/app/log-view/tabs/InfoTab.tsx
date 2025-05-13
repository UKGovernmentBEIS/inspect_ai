import { FC, RefObject, useMemo, useRef } from "react";
import {
  EvalError,
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
} from "../../../@types/log";
import { SampleSummary } from "../../../client/api/types";
import { MessageBand } from "../../../components/MessageBand";
import { kLogViewInfoTabId } from "../../../constants";
import { useTotalSampleCount } from "../../../state/hooks";
import { PlanCard } from "../../plan/PlanCard";
import { TaskErrorCard } from "../error/TaskErrorPanel";

// Individual hook for Info tab
export const useInfoTabConfig = (
  evalSpec: EvalSpec | undefined,
  evalPlan: EvalPlan | undefined,
  evalError: EvalError | undefined | null,
  evalResults: EvalResults | undefined | null,
) => {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const totalSampleCount = useTotalSampleCount();
  return useMemo(() => {
    return {
      id: kLogViewInfoTabId,
      label: "Info",
      scrollable: true,
      component: InfoTab,
      componentProps: {
        evalSpec,
        evalPlan,
        evalError,
        evalResults,
        sampleCount: totalSampleCount,
        scrollRef,
      },
      scrollRef,
    };
  }, [evalSpec, evalPlan, evalError, evalResults, totalSampleCount]);
};

interface InfoTabProps {
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  evalResults?: EvalResults;
  samples?: SampleSummary[];
  evalStatus?: "started" | "error" | "cancelled" | "success";
  evalError?: EvalError;
  sampleCount?: number;
  scrollRef: RefObject<HTMLDivElement | null>;
}

export const InfoTab: FC<InfoTabProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStatus,
  evalError,
  sampleCount,
  scrollRef,
}) => {
  const showWarning =
    sampleCount === 0 &&
    evalStatus === "success" &&
    evalSpec?.dataset.samples &&
    evalSpec.dataset.samples > 0;

  return (
    <div style={{ width: "100%" }}>
      {showWarning ? (
        <MessageBand
          id="sample-too-large"
          message="Unable to display samples (this evaluation log may be too large)."
          type="warning"
        />
      ) : (
        ""
      )}
      <div style={{ padding: "0.5em 1em 0 1em", width: "100%" }}>
        <PlanCard
          evalSpec={evalSpec}
          evalPlan={evalPlan}
          scores={evalResults?.scores}
          scrollRef={scrollRef}
        />
        {evalStatus === "error" && evalError ? (
          <TaskErrorCard error={evalError} />
        ) : undefined}
      </div>
    </div>
  );
};
