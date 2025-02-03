import clsx from "clsx";
import { EvalLogHeader } from "../../api/types";
import styles from "./EvalStatus.module.css";
import { SidebarScoreView } from "./SidebarScoreView";
import { SidebarScoresView } from "./SidebarScoresView";

interface EvalStatusProps {
  logHeader?: EvalLogHeader;
}

export const EvalStatus: React.FC<EvalStatusProps> = ({ logHeader }) => {
  switch (logHeader?.status) {
    case "error":
      return <StatusError message="Error" />;

    case "cancelled":
      return <StatusCancelled message="Cancelled" />;

    case "started":
      return <StatusRunning message="Running" />;

    default:
      if (logHeader?.results?.scores && logHeader.results?.scores.length > 0) {
        if (logHeader.results.scores.length === 1) {
          return <SidebarScoreView scorer={logHeader.results.scores[0]} />;
        } else {
          return <SidebarScoresView scores={logHeader.results.scores} />;
        }
      } else {
        return null;
      }
  }
};

interface StatusProps {
  message: string;
}

const StatusCancelled: React.FC<StatusProps> = ({ message }) => {
  return (
    <div
      className={clsx(
        "text-style-secondary",
        "text-style-label",
        "text-size-small",
        styles.cancelled,
      )}
    >
      {message}
    </div>
  );
};

const StatusRunning: React.FC<StatusProps> = ({ message }) => {
  return (
    <div
      className={clsx(
        "text-style-secondary",
        "text-style-label",
        "text-size-small",
        styles.running,
      )}
    >
      <div>{message}</div>
    </div>
  );
};

const StatusError: React.FC<StatusProps> = ({ message }) => {
  return <div className={clsx(styles.error, "text-size-small")}>{message}</div>;
};
