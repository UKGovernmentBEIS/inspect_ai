import clsx from "clsx";
import { FC, Ref } from "react";
import { ApplicationIcons } from "../../../../appearance/icons";

import styles from "./TodoWriteInput.module.css";

interface ToolTodo {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

const toToolTodos = (obj: unknown): ToolTodo[] => {
  if (
    Array.isArray(obj) &&
    obj.every((item) => typeof item === "object") &&
    obj.every((item) => item !== null && "content" in item && "status" in item)
  ) {
    return obj as ToolTodo[];
  } else {
    return [];
  }
};

export const TodoWriteInput: FC<{
  contents: unknown;
  parentRef: Ref<HTMLDivElement>;
}> = ({ contents, parentRef }) => {
  const todoItems = toToolTodos(contents);
  return (
    <div ref={parentRef} className={clsx(styles.todoList)}>
      {todoItems.map((todo) => {
        return (
          <>
            <i
              className={clsx(
                todo.status === "completed"
                  ? ApplicationIcons.checkbox.checked
                  : ApplicationIcons.checkbox.unchecked,
                "text-size-smallest",
              )}
            />
            <span
              className={clsx(
                styles.todoItem,
                "text-size-smallest",
                todo.status === "in_progress" ? styles.inProgress : undefined,
              )}
            >
              {todo.content}
            </span>
          </>
        );
      })}
    </div>
  );
};
