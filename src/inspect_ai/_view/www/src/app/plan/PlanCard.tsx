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
  const generate_config = evalPlan?.config;
  const generate_record: Record<string, unknown> = Object.fromEntries(
    Object.entries(generate_config || {}),
  );

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

      {Object.keys(generate_record).length > 0 && (
        <Card>
          <CardHeader label="Generate Config" />
          <CardBody id={"task-generate-config"}>
            <MetaDataView
              key={`plan-md-generate-config`}
              className={"text-size-small"}
              entries={generate_record}
              tableOptions="sm"
            />
          </CardBody>
        </Card>
      )}

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
