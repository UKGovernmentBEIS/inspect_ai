import clsx from "clsx";
import { FC, ReactNode } from "react";
import { ModelUsage1 } from "../../@types/log";
import { ModelUsagePanel } from "./ModelUsagePanel";
import styles from "./TokenTable.module.css";

interface TokenTableProps {
  className?: string | string[];
  children?: ReactNode;
}

export const TokenTable: FC<TokenTableProps> = ({ className, children }) => {
  return (
    <table
      className={clsx(
        "table",
        "table-sm",
        "text-size-smaller",
        styles.table,
        className,
      )}
    >
      {children}
    </table>
  );
};

export const TokenHeader = () => {
  return (
    <thead>
      <tr>
        <td></td>
        <td
          colSpan={3}
          className={clsx(
            "card-subheading",
            styles.tableTokens,
            "text-size-small",
            "text-style-label",
            "text-style-secondary",
          )}
          align="center"
        >
          Tokens
        </td>
      </tr>
      <tr>
        <th
          className={clsx(
            styles.tableH,
            "text-sixe-small",
            "text-style-label",
            "text-style-secondary",
          )}
        >
          Model
        </th>
        <th
          className={clsx(
            styles.tableH,
            "text-sixe-small",
            "text-style-label",
            "text-style-secondary",
          )}
        >
          Usage
        </th>
      </tr>
    </thead>
  );
};

interface TokenRowProps {
  model: string;
  usage: ModelUsage1;
}

export const TokenRow: FC<TokenRowProps> = ({ model, usage }) => {
  return (
    <tr>
      <td>
        <div className={clsx(styles.model, styles.cellContents)}>{model}</div>
      </td>
      <td>
        <ModelUsagePanel usage={usage} className={clsx(styles.cellContents)} />
      </td>
    </tr>
  );
};
