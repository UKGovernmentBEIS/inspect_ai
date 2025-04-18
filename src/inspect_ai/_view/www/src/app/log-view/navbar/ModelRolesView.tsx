import { FC } from "react";

import clsx from "clsx";
import { ModelRoles } from "../../../@types/log";
import styles from "./ModelRolesView.module.css";

interface ModelRolesViewProps {
  roles: ModelRoles;
}

/**
 * Renders the Navbar
 */
export const ModelRolesView: FC<ModelRolesViewProps> = ({ roles }) => {
  roles = roles || {};

  // Render as a single line if there is only a single
  // model role
  const singleLine = Object.keys(roles).length !== 1;

  // Render a layout of model roles
  const modelEls = Object.keys(roles).map((key) => {
    const role = key;
    const roleData = roles[role];
    const model = roleData.model;
    return (
      <div
        className={clsx(
          singleLine ? styles.grid : undefined,
          "text-style-secondary",
          "text-size-smallest",
        )}
        key={key}
      >
        <span className={clsx("text-style-label")}>{role}:</span>
        <span>{model}</span>
      </div>
    );
  });
  return modelEls.length > 0 ? (
    <div className={styles.container}>{modelEls}</div>
  ) : undefined;
};
