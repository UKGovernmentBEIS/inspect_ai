import { ReactNode } from "react";

interface EmptyPanelProps {
  children?: ReactNode;
}

export const EmptyPanel: React.FC<EmptyPanelProps> = ({ children }) => {
  return (
    <div className={"empty-panel"}>
      <div className={"container"}>
        <div>{children}</div>
      </div>
    </div>
  );
};
