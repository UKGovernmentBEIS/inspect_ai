import clsx from "clsx";
import { ApplicationIcons } from "../../../appearance/icons";
import styles from "./EventRow.module.css";

interface EventRowProps {
  title: string;
  icon: string;
  className?: string | string[];
  children?: React.ReactNode | React.ReactNode[];
}
/**
 * Renders the EventRow component.
 */
export const EventRow: React.FC<EventRowProps> = ({
  title,
  icon,
  className,
  children,
}) => {
  const contentEl = title ? (
    <div className={clsx("text-size-small", styles.title, className)}>
      <i className={icon || ApplicationIcons.metadata} />
      <div className={clsx("text-style-label")}>{title}</div>
      <div>{children}</div>
    </div>
  ) : (
    ""
  );

  const card = <div className={clsx("card", styles.contents)}>{contentEl}</div>;
  return card;
};
