import clsx from "clsx";
import { FC, ReactNode } from "react";
import styles from "./EventSection.module.css";

interface EventSectionProps {
  title: string;
  children: ReactNode;
  className?: string | string[];
}

/**
 * Renders the Event Section component.
 */
export const EventSection: FC<EventSectionProps> = ({
  title,
  children,
  className,
}) => {
  return (
    <div className={clsx(styles.container, className)}>
      <div
        className={clsx("text-size-small", "text-style-label", styles.title)}
      >
        {title}
      </div>
      {children}
    </div>
  );
};
