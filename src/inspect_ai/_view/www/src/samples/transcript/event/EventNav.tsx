import clsx from "clsx";

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
export const EventNav: React.FC<EventNavProps> = ({
  target,
  title,
  selectedNav,
  setSelectedNav,
}) => {
  const active = target === selectedNav;
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
        onClick={() => {
          setSelectedNav(target);
        }}
      >
        {title}
      </button>
    </li>
  );
};
