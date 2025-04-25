import { EvalStats } from "../../@types/log";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { ModelTokenTable } from "./ModelTokenTable";

import { FC } from "react";
import styles from "./UsageCard.module.css";

const kUsageCardBodyId = "usage-card-body";

interface UsageCardProps {
  stats?: EvalStats;
}

/**
 * Renders the UsageCard component.
 */
export const UsageCard: FC<UsageCardProps> = ({ stats }) => {
  if (!stats) {
    return null;
  }

  return (
    <Card>
      <CardHeader label="Usage" />
      <CardBody id={kUsageCardBodyId}>
        <div className={styles.wrapper}>
          <div className={styles.col2}>
            <ModelTokenTable model_usage={stats.model_usage} />
          </div>
        </div>
      </CardBody>
    </Card>
  );
};
