import clsx from "clsx";
import { FC } from "react";
import { ContentImage, ContentText } from "../../../../@types/log";
import styles from "./ToolOutput.module.css";

interface ToolOutputProps {
  output: string | number | boolean | (ContentText | ContentImage)[];
}

/**
 * Renders the ToolOutput component.
 */
export const ToolOutput: FC<ToolOutputProps> = ({ output }) => {
  // If there is no output, don't show the tool
  if (!output) {
    return null;
  }

  // First process an array or object into a string
  const outputs = [];
  if (Array.isArray(output)) {
    output.forEach((out, idx) => {
      const key = `tool-output-${idx}`;
      if (out.type === "text") {
        outputs.push(<ToolTextOutput text={out.text} key={key} />);
      } else {
        if (out.image.startsWith("data:")) {
          outputs.push(
            <img
              className={clsx(styles.toolImage)}
              src={out.image}
              key={key}
            />,
          );
        } else {
          outputs.push(<ToolTextOutput text={String(out.image)} key={key} />);
        }
      }
    });
  } else {
    outputs.push(
      <ToolTextOutput text={String(output)} key={"tool-output-single"} />,
    );
  }
  return <div className={clsx(styles.output)}>{outputs}</div>;
};

interface ToolTextOutputProps {
  text: string;
}

/**
 * Renders the ToolTextOutput component.
 */
const ToolTextOutput: FC<ToolTextOutputProps> = ({ text }) => {
  return (
    <pre className={clsx(styles.textOutput, "tool-output")}>
      <code className={clsx("sourceCode", styles.textCode)}>{text.trim()}</code>
    </pre>
  );
};
