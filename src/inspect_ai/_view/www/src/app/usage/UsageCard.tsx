import clsx from "clsx";
import { EvalStats } from "../../@types/log";
import { FontSize } from "../../app/appearance/fonts";
import { ApplicationIcons } from "../../app/appearance/icons";
import { MetaDataView } from "../../app/content/MetaDataView";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { formatDuration } from "../../utils/format";
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

  const totalDuration = formatDuration(
    new Date(stats.started_at),
    new Date(stats.completed_at),
  );
  const usageMetadataStyle = {
    fontSize: FontSize.smaller,
  };

  return (
    <Card>
      <CardHeader icon={ApplicationIcons.usage} label="Usage" />
      <CardBody id={kUsageCardBodyId}>
        <div className={styles.wrapper}>
          <div className={styles.col1}>
            <div
              className={clsx(
                "text-size-smaller",
                "text-style-label",
                "text-style-secondary",
              )}
            >
              Duration
            </div>
            <MetaDataView
              entries={{
                ["Start"]: new Date(stats.started_at).toLocaleString(),
                ["End"]: new Date(stats.completed_at).toLocaleString(),
                ["Duration"]: totalDuration,
              }}
              tableOptions="borderless,sm"
              style={usageMetadataStyle}
            />
          </div>

          <div className={styles.col2}>
            <ModelTokenTable model_usage={stats.model_usage} />
          </div>
        </div>
      </CardBody>
    </Card>
  );
};
