import clsx from "clsx";
import { FC, ReactNode } from "react";
import styles from "./EventSection.module.css";

interface EventSectionProps {
  title: string;
  children: ReactNode;
  actions?: ReactNode | ReactNode[];
  className?: string | string[];
}

/**
 * Renders the Event Section component.
 */
export const EventSection: FC<EventSectionProps> = ({
  title,
  children,
  actions,
  className,
}) => {
  return (
    <div className={clsx(styles.container, className)}>
      <div className={clsx(styles.titleRow)}>
        <div
          className={clsx("text-size-small", "text-style-label", styles.title)}
        >
          {title}
          {actions ? (
            <div className={clsx(styles.actions)}>{actions}</div>
          ) : null}
        </div>
      </div>
      {children}
    </div>
  );
};
