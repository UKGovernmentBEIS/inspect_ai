import { EvalStats } from "../../@types/log";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { ModelTokenTable } from "./ModelTokenTable";

import { FC } from "react";
import styles from "./UsageCard.module.css";

const kModelUsageCardBodyId = "model-usage-card-body";
const kRoleUsageCardBodyId = "role-usage-card-body";

interface UsageCardProps {
  stats?: EvalStats;
}

/**
 * Renders the UsageCard component as two separate cards side by side.
 */
export const UsageCard: FC<UsageCardProps> = ({ stats }) => {
  if (!stats) {
    return null;
  }

  const hasRoleUsage =
    stats.role_usage && Object.keys(stats.role_usage).length > 0;

  return (
    <div className={styles.cardsContainer}>
      <Card>
        <CardHeader label="Model Usage" />
        <CardBody id={kModelUsageCardBodyId}>
          <ModelTokenTable model_usage={stats.model_usage} />
        </CardBody>
      </Card>
      {hasRoleUsage && (
        <Card>
          <CardHeader label="Role Usage" />
          <CardBody id={kRoleUsageCardBodyId}>
            <ModelTokenTable model_usage={stats.role_usage} />
          </CardBody>
        </Card>
      )}
    </div>
  );
};
