import clsx from "clsx";
import { ApplicationIcons } from "../appearance/icons";
import "./Card.css";

interface CardHeaderProps {
  id?: string;
  icon?: string;
  label?: string;
  className?: string;
  children?: React.ReactNode;
}

interface CardBodyProps {
  id?: string;
  children?: React.ReactNode;
}

interface CardProps {
  id?: string;
  children?: React.ReactNode;
}

interface CardCollapsingHeaderProps {
  id: string;
  icon: string;
  label: string;
  cardBodyId: string;
  children?: React.ReactNode;
}

export const CardHeader: React.FC<CardHeaderProps> = ({
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

export const CardBody: React.FC<CardBodyProps> = ({ id, children }) => {
  return (
    <div className={"card-body"} id={id || ""}>
      {children}
    </div>
  );
};

export const Card: React.FC<CardProps> = ({ id, children }) => {
  return (
    <div className={"card"} id={id}>
      {children}
    </div>
  );
};

export const CardCollapsingHeader: React.FC<CardCollapsingHeaderProps> = ({
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
