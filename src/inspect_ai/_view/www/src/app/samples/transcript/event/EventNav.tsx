import clsx from "clsx";

import { FC, useCallback } from "react";
import styles from "./EventNav.module.css";

interface EventNavProps {
  target: string;
  title: string;
  selectedNav: string;
  setSelectedNav: (nav: string) => void;
}
/**
 * Component to render a single navigation item.
 */
export const EventNav: FC<EventNavProps> = ({
  target,
  title,
  selectedNav,
  setSelectedNav,
}) => {
  const active = target === selectedNav;

  const handleClick = useCallback(() => {
    setSelectedNav(target);
  }, [setSelectedNav, target]);

  return (
    <li className="nav-item">
      <button
        type="button"
        role="tab"
        aria-controls={target}
        aria-selected={active}
        className={clsx(
          "nav-link",
          active ? "active " : "",
          "text-style-label",
          "text-size-small",
          styles.tab,
        )}
        onClick={handleClick}
      >
        {title}
      </button>
    </li>
  );
};
