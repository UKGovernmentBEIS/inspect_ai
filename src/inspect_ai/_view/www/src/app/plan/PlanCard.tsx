import { FC, RefObject } from "react";
import { EvalPlan, EvalScore, EvalSpec } from "../../@types/log";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { RecordTree } from "../content/RecordTree";
import { PlanDetailView } from "./PlanDetailView";

interface PlanCardProps {
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  scores?: EvalScore[];
  scrollRef: RefObject<HTMLDivElement | null>;
}

/**
 * Renders the plan card
 */
export const PlanCard: FC<PlanCardProps> = ({
  evalSpec,
  evalPlan,
  scores,
  scrollRef,
}) => {
  const metadata = evalSpec?.metadata || {};

  return (
    <>
      <Card>
        <CardHeader label="Summary" />
        <CardBody id={"task-plan-card-body"}>
          <PlanDetailView
            evaluation={evalSpec}
            plan={evalPlan}
            scores={scores}
          />
        </CardBody>
      </Card>

      {Object.keys(metadata).length > 0 && (
        <Card>
          <CardHeader label="Metadata" />
          <CardBody id={"task-metadata`"}>
            <RecordTree
              id={"plan-md-metadata"}
              record={metadata}
              scrollRef={scrollRef}
            />
          </CardBody>
        </Card>
      )}
    </>
  );
};
