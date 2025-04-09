import { FC } from "react";
import { EvalPlan, EvalScore, EvalSpec } from "../../@types/log";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { ApplicationIcons } from "../appearance/icons";
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
  return (
    <Card>
      <CardHeader icon={ApplicationIcons.config} label="Config" />
      <CardBody id={"task-plan-card-body"}>
        <PlanDetailView evaluation={evalSpec} plan={evalPlan} scores={scores} />
      </CardBody>
    </Card>
  );
};
