// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").StepEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const StepEventView = ({ event }) => {
  if (event.action === "begin") {
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
      } else {
        return ApplicationIcons.step;
      }
    };

    return html`<div
      style=${{
        display: "grid",
        gridTemplateRows: "auto auto",
        paddingBottom: "0.5em",
      }}
    >
      <div
        style=${{
          display: "inline-block",
          justifySelf: "left",
          borderTop: "1px solid var(--bs-light-border-subtle)",
          borderLeft: "1px solid var(--bs-light-border-subtle)",
          borderRight: "1px solid var(--bs-light-border-subtle)",
          padding: "0.1em 0.3em",
          fontWeight: 600,
        }}
      >
        <i class=${icon()} style=${{ marginRight: "0.2em" }} />${event.name}
      </div>
      <div
        style=${{
          width: "100%",
          borderBottom: "1px solid var(--bs-light-border-subtle)",
        }}
      ></div>
    </div>`;
  } else {
    return html`<div
      style=${{
        width: "100%",
        borderBottom: "1px solid var(--bs-light-border-subtle)",
      }}
    ></div>`;
  }
};
