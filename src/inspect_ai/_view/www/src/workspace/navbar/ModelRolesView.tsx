import { FC } from "react";
import { ModelRoles } from "../../types/log";

import clsx from "clsx";
import styles from "./ModelRolesView.module.css";

interface ModelRolesViewProps {
  roles: ModelRoles;
}

/**
 * Renders the Navbar
 */
export const ModelRolesView: FC<ModelRolesViewProps> = ({ roles }) => {
  roles = roles || {};
  const modelEls = Object.keys(roles).map((key, index) => {
    const role = key;
    const roleData = roles[role];
    const model = roleData.model;
    return (
      <div
        className={clsx(
          styles.grid,
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
  return <div className={styles.container}>{modelEls}</div>;
};
