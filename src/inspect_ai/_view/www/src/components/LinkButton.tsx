import clsx from "clsx";
import { FC } from "react";
import styles from "./LinkButton.module.css";

interface LinkButtonProps {
  id?: string;
  text?: string;
  icon?: string;
  onClick: () => void;
  className?: string | string[];
}

/**
 * LightboxCarousel component provides a carousel with lightbox functionality.
 */
export const LinkButton: FC<LinkButtonProps> = ({
  id,
  text,
  icon,
  className,
  onClick,
}) => {
  return (
    <button
      id={id}
      onClick={onClick}
      className={clsx(className, styles.button, "text-size-smaller")}
    >
      {icon ? <i className={clsx(icon)}></i> : undefined}
      {text ? <div className={clsx(styles.label)}>{text}</div> : undefined}
    </button>
  );
};
