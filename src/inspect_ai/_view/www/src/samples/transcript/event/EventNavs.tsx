import clsx from "clsx";
import { EventNav } from "./EventNav";

import { FC } from "react";
import styles from "./EventNavs.module.css";

interface EventNavsProps {
  navs: Array<{ id: string; title: string; target: string }>;
  selectedNav: string;
  setSelectedNav: (target: string) => void;
}

/**
 * Component to render navigation items.
 */
export const EventNavs: FC<EventNavsProps> = ({
  navs,
  selectedNav,
  setSelectedNav,
}) => {
  return (
    <ul
      className={clsx("nav", "nav-pills", styles.navs)}
      role="tablist"
      aria-orientation="horizontal"
    >
      {navs.map((nav) => {
        return (
          <EventNav
            key={nav.title}
            target={nav.target}
            title={nav.title}
            selectedNav={selectedNav}
            setSelectedNav={setSelectedNav}
          />
        );
      })}
    </ul>
  );
};
