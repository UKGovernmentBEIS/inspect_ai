import clsx from "clsx";
import { ButtonHTMLAttributes, FC, ReactNode } from "react";
import { ToolButton } from "../../components/ToolButton";

import styles from "./NavbarButton.module.css";

interface NavbarButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  label: string | ReactNode;
  className?: string | string[];
  icon?: string;
  latched?: boolean;
}

export const NavbarButton: FC<NavbarButtonProps> = ({
  label,
  className,
  icon,
  latched,
  ...rest
}) => {
  return (
    <ToolButton
      label={label}
      className={clsx(className, styles.navbarButton)}
      icon={icon}
      latched={latched}
      {...rest}
    />
  );
};
