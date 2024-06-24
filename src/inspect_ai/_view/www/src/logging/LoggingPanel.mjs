import { html } from "htm/preact";

import { icons, colors } from "../Constants.mjs";
import { RenderedContent } from "../components/RenderedContent.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";

export const LoggingPanel = ({ logging, context }) => {
  if (!logging || logging.length === 0) {
    return html`<${EmptyPanel} style=${{
      fontSize: "0.8rem",
    }}>No Messages</${EmptyPanel}>`;
  }

  return html`
    <table
      class="table table-hover table-sm"
      style=${{
        fontSize: "0.9rem",
        width: "100%",
        marginBottom: "0rem",
        tableLayout: "fixed",
        alignSelf: "flex-start",
      }}
    >
      <colgroup>
        <col span="1" style="width: 1.6rem;" />
        <col span="1" style="width: 10rem;" />
        <col span="1" />
      </colgroup>
      <tbody>
        ${logging.map((log, index) => {
          const logDate = new Date(log.created);
          return html`<tr>
            <td>
              <i
                class="${icon(log.level)}"
                style=${{
                  marginLeft: "0.5rem",
                  fontSize: "0.7rem",
                  color: color(log.level),
                }}
              ></i>
            </td>
            <td>
              <pre
                style=${{
                  fontSize: "0.7rem",
                  marginLeft: "0.2rem",
                  marginTop: "0.2rem",
                  marginBottom: "0.2rem",
                }}
              >
              ${logDate.toLocaleDateString()} ${logDate.toLocaleTimeString()}
              </pre
              >
            </td>
            <td>
              <${RenderedContent}
                id="log-message-${index}"
                entry=${{
                  name: "log_message",
                  value: log.message,
                }}
                context=${context}
                defaultRendering=${(val) => {
                  return html`<pre
                    style=${{
                      marginTop: "0.3rem",
                      marginBottom: "0.2rem",
                      fontSize: "0.7rem",
                      whiteSpace: "pre-wrap",
                    }}
                  >
${val}</pre
                  >`;
                }}
              />
            </td>
          </tr>`;
        })}
      </tbody>
    </table>
  `;
};

const icon = (level) => {
  const icon = icons.logging[level.toLowerCase()];
  return icon || icons.logging.notset;
};

const color = (level) => {
  const color = colors.logging[level.toLowerCase()];
  return color || colors.debug;
};
