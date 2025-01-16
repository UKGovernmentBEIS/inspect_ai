export const EmptyPanel: React.FC = ({ children }) => {
  return (
    <div className={"empty-panel"}>
      <div className={"container"}>
        <div>{children}</div>
      </div>
    </div>
  );
};
