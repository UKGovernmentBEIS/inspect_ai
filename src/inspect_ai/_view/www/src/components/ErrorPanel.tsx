import { FC } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import "./ErrorPanel.css";

export interface DisplayError {
  message: string;
  stack?: string;
  displayStack?: boolean;
}

interface ErrorPanelProps {
  title: string;
  error: DisplayError;
}

export const ErrorPanel: FC<ErrorPanelProps> = ({ title, error }) => {
  const message = error.message;
  const stack = error.stack;

  return (
    <div className={"error-panel centered-flex"}>
      <div className={"error-panel-heading centered-flex"}>
        <div>
          <i className={`${ApplicationIcons.error} error-icon`}></i>
        </div>
        <div>{title || ""}</div>
      </div>
      <div className={"error-panel-body"}>
        <div>
          Error: {message || ""}
          {stack && error.displayStack !== false && (
            <pre className={"error-panel-stack"}>
              <code>at {stack}</code>
            </pre>
          )}
        </div>
      </div>
    </div>
  );
};
