import { FC } from "react";
import { ModelUsage, ModelUsage2 } from "../../@types/log";
import { TokenHeader, TokenRow, TokenTable } from "./TokenTable";

interface ModelTokenTableProps {
  model_usage: ModelUsage | ModelUsage2;
  className?: string | string[];
}

export const ModelTokenTable: FC<ModelTokenTableProps> = ({
  model_usage,
  className,
}) => {
  return (
    <TokenTable className={className}>
      <TokenHeader />
      <tbody>
        {Object.keys(model_usage).map((key) => {
          return <TokenRow key={key} model={key} usage={model_usage[key]} />;
        })}
      </tbody>
    </TokenTable>
  );
};
