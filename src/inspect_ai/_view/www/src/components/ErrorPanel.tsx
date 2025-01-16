import { ApplicationIcons } from "../appearance/icons";
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

export const ErrorPanel = (props: ErrorPanelProps) => {
  const message = props.error.message;
  const stack = props.error.stack;

  return (
    <div className={"error-panel centered-flex"}>
      <div className={"error-panel-heading centered-flex"}>
        <div>
          <i class={`${ApplicationIcons.error} error-icon`}></i>
        </div>
        <div>{props.title || ""}</div>
      </div>
      <div className={"error-panel-body"}>
        <div>
          Error: {message || ""}$
          {stack && props.error.displayStack !== false && (
            <pre className={"error-panel-stack"}>
              <code>at ${stack}</code>
            </pre>
          )}
        </div>
      </div>
    </div>
  );
};
