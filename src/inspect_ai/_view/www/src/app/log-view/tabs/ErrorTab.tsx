import { FC, RefObject, useMemo, useRef } from "react";
import { EvalError } from "../../../@types/log";
import { kLogViewErrorTabId } from "../../../constants";
import { TaskErrorCard } from "../error/TaskErrorPanel";

// Individual hook for Info tab
export const useErrorTabConfig = (evalError: EvalError | undefined | null) => {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  return useMemo(() => {
    return {
      id: kLogViewErrorTabId,
      label: "Error",
      scrollable: true,
      component: ErrorTab,
      componentProps: {
        evalError,
        scrollRef,
      },
      scrollRef,
    };
  }, [evalError]);
};

interface ErrorTabProps {
  evalError: EvalError | undefined | null;
  scrollRef: RefObject<HTMLDivElement | null>;
}

export const ErrorTab: FC<ErrorTabProps> = ({ evalError }) => {
  return (
    <div style={{ width: "100%" }}>
      <div style={{ padding: "0.5em 1em 0 1em", width: "100%" }}>
        <TaskErrorCard
          error={
            evalError || {
              message: "Unknown error",
              traceback: "",
              traceback_ansi: "",
            }
          }
        />{" "}
      </div>
    </div>
  );
};
