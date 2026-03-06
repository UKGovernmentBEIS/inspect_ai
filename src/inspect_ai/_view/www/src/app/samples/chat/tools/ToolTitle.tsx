import clsx from "clsx";
import { FC, Fragment } from "react";
import styles from "./ToolTitle.module.css";
interface ToolTitleProps {
  title: string;
  description?: string;
}

/**
 * Renders the ToolCallView component.
 */
export const ToolTitle: FC<ToolTitleProps> = ({ title, description }) => {
  return (
    <Fragment>
      <i className={clsx("bi", "bi-tools", styles.image)} />
      <code className={clsx("text-size-small", styles.toolTitle)}>{title}</code>
      {description ? (
        <span className={clsx(styles.description, "text-size-smallest")}>
          - {description}
        </span>
      ) : undefined}
    </Fragment>
  );
};
