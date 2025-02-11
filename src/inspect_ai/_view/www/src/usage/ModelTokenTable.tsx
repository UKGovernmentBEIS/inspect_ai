import { TokenHeader, TokenRow, TokenTable } from "./TokenTable";

interface ModelTokenTable {
  model_usage: any;
  className?: string | string[];
}

export const ModelTokenTable: React.FC<ModelTokenTable> = ({
  model_usage,
  className,
}) => {
  return (
    <TokenTable className={className}>
      <TokenHeader />
      <tbody>
        {Object.keys(model_usage).map((key) => {
          return (
            <TokenRow
              key={key}
              model={`${key}-token-row`}
              usage={model_usage[key]}
            />
          );
        })}
      </tbody>
    </TokenTable>
  );
};
