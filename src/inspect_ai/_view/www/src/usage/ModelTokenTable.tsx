import { TokenHeader, TokenRow, TokenTable } from "./TokenTable";

interface ModelTokenTable {
  model_usage: any;
  style?: React.CSSProperties;
}

export const ModelTokenTable: React.FC<ModelTokenTable> = ({
  model_usage,
  style,
}) => {
  return (
    <TokenTable style={style}>
      <TokenHeader />
      <tbody>
        {Object.keys(model_usage).map((key) => {
          return <TokenRow model={key} usage={model_usage[key]} />;
        })}
      </tbody>
    </TokenTable>
  );
};
