import { FC } from "react";
import { ToolButton } from "../../components/ToolButton";

interface CollapseLogsToggleProps {
  collapseLogs: boolean;
  onToggle: (collapse: boolean) => void;
}

export const CollapseLogsToggle: FC<CollapseLogsToggleProps> = ({
  collapseLogs,
  onToggle,
}) => {
  return (
    <ToolButton
      label={`Retried Logs ${collapseLogs ? "Hidden" : "Shown"}`}
      icon="bi bi-layers"
      classes="text-size-smallest text-style-secondary"
      latched={collapseLogs}
      onClick={() => onToggle(!collapseLogs)}
      style={{ padding: "0em 0.5em" }}
      title={
        collapseLogs
          ? "Only showing the latest log file for each task"
          : "Showing all log files including retries"
      }
    />
  );
};
