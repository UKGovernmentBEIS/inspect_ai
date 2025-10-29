import { FC } from "react";
import { useNavigate } from "react-router-dom";
import { SegmentedControl } from "../../components/SegmentedControl";

interface ViewSegmentControlProps {
  selectedSegment: "logs" | "samples";
}

const segments = [
  { id: "logs", label: "logs" },
  { id: "samples", label: "samples" },
];

export const ViewSegmentedControl: FC<ViewSegmentControlProps> = ({
  selectedSegment,
}) => {
  const navigate = useNavigate();

  return (
    <SegmentedControl
      segments={segments}
      selectedId={selectedSegment}
      onSegmentChange={(segment) => {
        navigate(`/${segment}`);
      }}
    />
  );
};
