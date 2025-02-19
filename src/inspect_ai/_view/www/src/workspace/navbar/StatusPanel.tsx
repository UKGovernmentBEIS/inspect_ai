import clsx from "clsx";
import { ApplicationIcons } from "../../appearance/icons";
import styles from "./StatusPanel.module.css";

interface StatusProps {
  sampleCount: number;
}

export const CancelledPanel: React.FC<StatusProps> = ({ sampleCount }) => {
  return (
    <StatusPanel
      icon={ApplicationIcons.logging["info"]}
      status="Cancelled"
      sampleCount={sampleCount}
    />
  );
};

export const ErroredPanel: React.FC<StatusProps> = ({ sampleCount }) => {
  return (
    <StatusPanel
      icon={ApplicationIcons.logging["error"]}
      status="Task Failed"
      sampleCount={sampleCount}
    />
  );
};

export const RunningPanel: React.FC<StatusProps> = ({ sampleCount }) => {
  return (
    <StatusPanel
      icon={ApplicationIcons.running}
      status="Running"
      sampleCount={sampleCount}
    />
  );
};

interface StatusPanelProps {
  icon: string;
  status: string;
  sampleCount: number;
}

const StatusPanel: React.FC<StatusPanelProps> = ({
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
