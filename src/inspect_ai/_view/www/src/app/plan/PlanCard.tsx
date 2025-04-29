import { FC } from "react";
import { EvalPlan, EvalScore, EvalSpec } from "../../@types/log";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { MetaDataView } from "../content/MetaDataView";
import { PlanDetailView } from "./PlanDetailView";

interface PlanCardProps {
  evalSpec?: EvalSpec;
  evalPlan?: EvalPlan;
  scores?: EvalScore[];
}

/**
 * Renders the plan card
 */
export const PlanCard: FC<PlanCardProps> = ({ evalSpec, evalPlan, scores }) => {
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
            <MetaDataView
              key={`plan-md-metadata`}
              className={"text-size-small"}
              entries={metadata}
              tableOptions="sm"
            />
          </CardBody>
        </Card>
      )}
    </>
  );
};
