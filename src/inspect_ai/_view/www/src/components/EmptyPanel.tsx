interface EmptyPanelProps {
  children: React.ReactNode;
}

export const EmptyPanel = (props: EmptyPanelProps) => {
  return (
    <div className={"empty-panel"}>
      <div className={"container"}>
        <div>{props.children}</div>
      </div>
    </div>
  );
};
