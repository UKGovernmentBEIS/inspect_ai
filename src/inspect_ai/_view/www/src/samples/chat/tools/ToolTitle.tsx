import clsx from "clsx";
import { Fragment } from "react";
import styles from "./ToolTitle.module.css";
interface ToolTitleProps {
  title: string;
}

/**
 * Renders the ToolCallView component.
 */
export const ToolTitle: React.FC<ToolTitleProps> = ({ title }) => {
  return (
    <Fragment>
      <i className={clsx("bi", "bi-tools", styles.styles)} />
      <code className={"text-size-small"}>{title}</code>
    </Fragment>
  );
};
