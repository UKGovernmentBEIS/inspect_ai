// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").StepEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StepEventViewStart = ({ event }) => {
  const icon = () => {
    if (event.type === "solver") {
      switch (event.name) {
        case "chain_of_thought":
          return ApplicationIcons.solvers.chain_of_thought;
        case "generate":
          return ApplicationIcons.solvers.generate;
        case "self_critique":
          return ApplicationIcons.solvers.self_critique;
        case "system_message":
          return ApplicationIcons.solvers.system_message;
        case "use_tools":
          return ApplicationIcons.solvers.use_tools;
        default:
          return ApplicationIcons.solvers.default;
      }
    } else if (event.type === "scorer") {
      return ApplicationIcons.scorer;
    } else {
      return ApplicationIcons.step;
    }
  };

  return html`<div
    style=${{
      display: "grid",
      gridTemplateRows: "max-content auto",
      marginBottom: "1em",
      borderBottom: "solid 1px var(--bs-light-border-subtle)"
    }}
  >
    <div
      style=${{
        display: "inline-block",
        justifySelf: "left",
        fontSize: FontSize.base,
        fontWeight: 500,
        ...TextStyle.label
      }}
    >
      <i class=${icon()} style=${{ marginRight: "0.2em" }} />${event.name}
    </div>
    <div
      style=${{
        width: "100%",
      }}
    ></div>
  </div>`;
};
