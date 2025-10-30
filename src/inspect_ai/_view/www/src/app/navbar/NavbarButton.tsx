import clsx from "clsx";
import { FC, ReactNode } from "react";
import { ToolButton } from "../../components/ToolButton";

import styles from "./NavbarButton.module.css";

interface NavbarButtonProps {
  label: string | ReactNode;
  className?: string | string[];
  icon?: string;
  latched?: boolean;
  onClick?: () => void;
}

export const NavbarButton: FC<NavbarButtonProps> = ({
  label,
  className,
  icon,
  latched,
  onClick,
}) => {
  return (
    <ToolButton
      label={label}
      className={clsx(className, styles.navbarButton)}
      icon={icon}
      latched={latched}
      onClick={onClick}
    />
  );
};
