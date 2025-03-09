import { clsx } from "clsx";
import { FC, MouseEvent, ReactElement, ReactNode, useCallback } from "react";
import { useProperty } from "../state/hooks";
import styles from "./NavPills.module.css";

interface NavPillChildProps {
  title: string;
  [key: string]: any;
}

interface NavPillsProps {
  id: string;
  children?: ReactElement<NavPillChildProps>[];
}

export const NavPills: FC<NavPillsProps> = ({ id, children }) => {
  const defaultNav = children ? children[0].props["title"] : "";
  const [activeItem, setActiveItem] = useProperty(id, "active", {
    defaultValue: defaultNav,
  });

  if (!activeItem || !children) {
    return undefined;
  }

  // Create Nav Pills for each child
  const navPills = children.map((nav, idx) => {
    const title =
      typeof nav === "object"
        ? nav["props"]?.title || `Tab ${idx}`
        : `Tab ${idx}`;
    return (
      <NavPill
        key={`nav-pill-contents-${idx}`}
        title={title}
        activeItem={activeItem}
        setActiveItem={setActiveItem}
      />
    );
  });

  // Wrap each of the children in a 'body' to control its visibility
  const navBodies = children.map((child, idx) => {
    return (
      <div
        key={`nav-pill-container-${idx}`}
        className={
          child["props"]?.title === activeItem ? styles.visible : styles.hidden
        }
      >
        {child}
      </div>
    );
  });

  return (
    <div>
      <ul
        className={clsx("nav", "nav-pills", styles.pills)}
        role="tablist"
        aria-orientation="horizontal"
      >
        {navPills}
      </ul>
      {navBodies}
    </div>
  );
};

interface NavPillProps {
  title: string;
  activeItem: string;
  setActiveItem: (item: string) => void;
  children?: ReactNode;
}

const NavPill: FC<NavPillProps> = ({
  title,
  activeItem,
  setActiveItem,
  children,
}) => {
  const active = activeItem === title;
  const handleClick = useCallback(
    (e: MouseEvent<HTMLButtonElement>) => {
      const target = (e.currentTarget as HTMLButtonElement).dataset.target;
      if (target) {
        setActiveItem(target);
      }
    },
    [setActiveItem],
  );

  return (
    <li className={"nav-item"}>
      <button
        type="button"
        role="tab"
        aria-selected={active}
        className={clsx(
          "nav-link",
          "text-style-label",
          active ? "active " : "",
          styles.pill,
        )}
        data-target={title}
        onClick={handleClick}
      >
        {title}
      </button>
      {children}
    </li>
  );
};
