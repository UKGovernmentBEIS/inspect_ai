import { FC } from "react";
import { SampleSummary } from "../../api/types";
import { MessageBand } from "../../components/MessageBand";
import { ModelCard } from "../../plan/ModelCard";
import { PlanCard } from "../../plan/PlanCard";
import {
  EvalError,
  EvalPlan,
  EvalResults,
  EvalSpec,
  EvalStats,
} from "../../types/log";
import { UsageCard } from "../../usage/UsageCard";
import { TaskErrorCard } from "../error/TaskErrorPanel";

interface PlanTabProps {
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  evalStats?: EvalStats;
  evalResults?: EvalResults;
  samples?: SampleSummary[];
  evalStatus?: "started" | "error" | "cancelled" | "success";
  evalError?: EvalError;
  sampleCount?: number;
}

export const InfoTab: FC<PlanTabProps> = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  evalStatus,
  evalError,
  sampleCount,
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
        />
        {evalSpec ? <ModelCard evalSpec={evalSpec} /> : undefined}
        {evalStatus !== "started" ? <UsageCard stats={evalStats} /> : undefined}
        {evalStatus === "error" && evalError ? (
          <TaskErrorCard error={evalError} />
        ) : undefined}
      </div>
    </div>
  );
};
