import { FC, ReactNode } from "react";

interface EmptyPanelProps {
  children?: ReactNode;
}

export const EmptyPanel: FC<EmptyPanelProps> = ({ children }) => {
  return (
    <div className={"empty-panel"}>
      <div className={"container"}>
        <div>{children}</div>
      </div>
    </div>
  );
};
