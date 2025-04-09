import clsx from "clsx";
import { FC, ReactNode } from "react";
import { ApplicationIcons } from "../app/appearance/icons";
import "./Card.css";

interface CardHeaderProps {
  id?: string;
  icon?: string;
  label?: string;
  className?: string;
  children?: ReactNode;
}

interface CardBodyProps {
  id?: string;
  children?: ReactNode;
  className?: string | string[];
}

interface CardProps {
  id?: string;
  children?: ReactNode;
  className?: string | string[];
}

interface CardCollapsingHeaderProps {
  id: string;
  icon: string;
  label: string;
  cardBodyId: string;
  children?: ReactNode;
}

export const CardHeader: FC<CardHeaderProps> = ({
  id,
  icon,
  label,
  className,
  children,
}) => {
  return (
    <div
      className={clsx("card-header-container", "text-style-label", className)}
      id={id || ""}
    >
      {icon ? (
        <i className={clsx("card-header-icon", icon)}></i>
      ) : (
        <span className={"card-header-icon"}></span>
      )}
      {label ? label : ""} {children}
    </div>
  );
};

export const CardBody: FC<CardBodyProps> = ({ id, children, className }) => {
  return (
    <div className={clsx("card-body", className)} id={id || ""}>
      {children}
    </div>
  );
};

export const Card: FC<CardProps> = ({ id, children, className }) => {
  return (
    <div className={clsx("card", className)} id={id}>
      {children}
    </div>
  );
};

export const CardCollapsingHeader: FC<CardCollapsingHeaderProps> = ({
  id,
  icon,
  label,
  cardBodyId,
  children,
}) => {
  return (
    <CardHeader
      id={id}
      className={clsx(
        "card-collaping-header",
        "container-fluid",
        "collapse",
        "show",
        "do-not-collapse-self",
      )}
    >
      <div
        className={clsx("card-collaping-header-container", "row", "row-cols-3")}
        data-bs-toggle="collapse"
        data-bs-target={`#${cardBodyId}`}
        aria-expanded="false"
        aria-controls={cardBodyId}
      >
        <div className={"card-collaping-header-icon"}>
          <i className={icon}></i>{" "}
          <span className="hide-when-collapsed">{label}</span>
        </div>
        <div className="hide-when-expanded card-collapsing-header-content">
          {children}
        </div>
        <div className={"card-collapsing-header-toggle"}>
          <i
            className={clsx(ApplicationIcons["toggle-right"], "toggle-rotated")}
          ></i>
        </div>
      </div>
    </CardHeader>
  );
};
