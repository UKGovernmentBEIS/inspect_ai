import { clsx } from "clsx";
import { FC, ReactElement, ReactNode, useState } from "react";
import styles from "./NavPills.module.css";

interface NavPillChildProps {
  title: string;
  [key: string]: any;
}

interface NavPillsProps {
  children?: ReactElement<NavPillChildProps>[];
}

export const NavPills: FC<NavPillsProps> = ({ children }) => {
  const [activeItem, setActiveItem] = useState(
    children ? children[0].props["title"] : null,
  );
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
        onClick={() => {
          setActiveItem(title);
        }}
      >
        {title}
      </button>
      {children}
    </li>
  );
};
