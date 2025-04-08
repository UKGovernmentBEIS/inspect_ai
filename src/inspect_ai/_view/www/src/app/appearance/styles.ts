import { CSSProperties } from "react";
import { FontSize, TextStyle } from "./fonts";

export const ApplicationStyles = {
  moreButton: {
    maxHeight: "1.8em",
    fontSize: FontSize.smaller,
    padding: "0 0.2em 0 0.2em",
    ...TextStyle.secondary,
  },
  threeLineClamp: {
    display: "-webkit-box",
    WebkitLineClamp: "3",
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  },
  lineClamp: (len: number): CSSProperties => {
    return {
      display: "-webkit-box",
      WebkitLineClamp: `${len}`,
      WebkitBoxOrient: "vertical",
      overflow: "hidden",
    };
  },
  wrapText: () => {
    return {
      whiteSpace: "nowrap",
      textOverflow: "ellipsis",
      overflow: "hidden",
    };
  },
  scoreFills: {
    green: {
      backgroundColor: "var(--bs-success)",
      borderColor: "var(--bs-success)",
      color: "var(--bs-body-bg)",
    },
    red: {
      backgroundColor: "var(--bs-danger)",
      borderColor: "var(--bs-danger)",
      color: "var(--bs-body-bg)",
    },
    orange: {
      backgroundColor: "var(--bs-orange)",
      borderColor: "var(--bs-orange)",
      color: "var(--bs-body-bg)",
    },
  },
};
