import clsx from "clsx";
import { FC } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import styles from "./StatusPanel.module.css";

interface StatusProps {
  sampleCount: number;
}

export const CancelledPanel: FC<StatusProps> = ({ sampleCount }) => {
  return (
    <StatusPanel
      icon={ApplicationIcons.logging["info"]}
      status="Cancelled"
      sampleCount={sampleCount}
    />
  );
};

export const ErroredPanel: FC<StatusProps> = ({ sampleCount }) => {
  return (
    <StatusPanel
      icon={ApplicationIcons.logging["error"]}
      status="Task Failed"
      sampleCount={sampleCount}
    />
  );
};

export const RunningPanel: FC<StatusProps> = ({ sampleCount }) => {
  return (
    <StatusPanel
      icon={ApplicationIcons.running}
      status="Running"
      sampleCount={sampleCount}
    />
  );
};

export interface StatusPanelProps {
  icon: string;
  status: string;
  sampleCount: number;
}

export const StatusPanel: FC<StatusPanelProps> = ({
  icon,
  status,
  sampleCount,
}) => {
  return (
    <div className={styles.statusPanel}>
      <i className={clsx(icon, styles.statusIcon)} style={{}} />
      <div>
        <div>{status}</div>
        <div>
          ({sampleCount} {sampleCount === 1 ? "sample" : "samples"})
        </div>
      </div>
    </div>
  );
};
