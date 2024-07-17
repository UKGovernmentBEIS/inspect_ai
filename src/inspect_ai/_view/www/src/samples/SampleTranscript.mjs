// @ts-check
import { html } from "htm/preact";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { ChatView } from "../components/ChatView.mjs";
import { ApplicationIcons } from "../appearance/Icons.mjs";

/**
 * Renders the SampleTranscript component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {import("../types/log").Transcript} params.transcript - The transcript to display.
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const SampleTranscript = ({ transcript }) => {
  const rows = transcript.map((e, index) => {
    const rendered = getRenderer(e, index);
    return html`<div>${e.timestamp}</div>
      <div>${e.event}</div>
      <div>${rendered()}</div>`;
  });

  return html`<div
    style=${{
      fontSize: "0.8em",
      display: "grid",
      gridTemplateColumns: "auto auto auto",
      columnGap: "1em",
    }}
  >
    ${rows}
  </div>`;
};

/**
 * Fetches the renderer for the event
 *
 * @param {import("../types/log").StateEvent | import("../types/log").StoreEvent | import("../types/log").ModelEvent | import("../types/log").LoggerEvent | import("../types/log").InfoEvent | import("../types/log").StepEvent | import("../types/log").SubtaskEvent} event - The event to fetch the renderer for
 * @param {number} index - The current event index
 * @returns {Function} - A function that returns the rendered event.
 */
const getRenderer = (event, index) => {
  switch (event.event) {
    case "info":
      return () => {
        return html`<b>INFO</b>`;
      };

    case "logger":
      return () => {
        return html`<b>LOGGER</b>`;
      };

    case "model":
      return () => {
        const contents = {};
        contents["model"] = html`<b>${event.model}</b>`;
        if (event.config && Object.keys(event.config).length > 0) {
          contents["config"] = html`<${MetaDataView}
            entries=${event.config}
          />`;
        }
        contents["input"] = html`<${ChatView}
          id="model-input-${index}"
          messages=${event.input}
        />`;
        const outputMessages = event.output.choices.map((choice) => {
          return choice.message;
        });
        contents["output"] = html`<${ChatView}
          id="model-output-${index}"
          messages=${outputMessages}
        />`;

        return html`<div
          style=${{
            display: "grid",
            gridTemplateColumns: "auto auto",
            columnGap: "1em",
          }}
        >
          ${Object.keys(contents).map((key) => {
            return html`<div>${key}</div>
              <div>${contents[key]}</div>`;
          })}
        </div>`;
      };

    case "state":
      return () => {
        const renderValue = (change) => {
          if (typeof change.value === "object") {
            if (change.value.content && change.value.source) {
              return html`<${ChatView}
                id="model-input-${index}"
                messages=${[change.value]}
              />`;
            }
            return change.value;
          } else {
            return change.value;
          }
        };

        const mutations = event.changes.map((change) => {
          return html`
            <div>${change.op}</div>
            <div>${change.path}</div>
            <div>${change.from}</div>
            <div>${renderValue(change)}</div>
          `;
        });

        return html`<div
          style=${{
            display: "grid",
            gridTemplateColumns: "auto auto auto auto",
            columnGap: "1em",
          }}
        >
          ${mutations}
        </div>`;
      };

    case "step":
      return () => {
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
              <i
                class=${icon()}
                style=${{ marginRight: "0.2em" }}
              />${event.name}
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

    case "store":
      return () => {
        return html`<b>STORE</b>`;
      };

    case "subtask":
      return () => {
        return html`<b>SUBTASK</b>`;
      };
  }
};
