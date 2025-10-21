import clsx from "clsx";
import { FC, ReactNode } from "react";
import { CopyButton } from "../../../../components/CopyButton";
import styles from "./EventSection.module.css";

interface EventSectionProps {
  title: string;
  children: ReactNode;
  copyContent?: string;
  className?: string | string[];
}

/**
 * Renders the Event Section component.
 */
export const EventSection: FC<EventSectionProps> = ({
  title,
  children,
  copyContent,
  className,
}) => {
  return (
    <div className={clsx(styles.container, className)}>
      <div className={clsx(styles.titleRow)}>
        <div
          className={clsx("text-size-small", "text-style-label", styles.title)}
        >
          {title}
          {copyContent ? (
            <CopyButton value={copyContent} ariaLabel="Copy to clipboard" />
          ) : null}
        </div>
      </div>
      {children}
    </div>
  );
};
