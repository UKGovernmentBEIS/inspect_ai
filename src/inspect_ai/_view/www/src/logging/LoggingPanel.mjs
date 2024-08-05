import { html } from "htm/preact";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { ApplicationColors } from "../appearance/Colors.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { DownloadPanel } from "../components/DownloadPanel.mjs";
import { RenderedContent } from "../components/RenderedContent.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";

export const LoggingPanel = ({ logFile, capabilities, logging, context }) => {
  if (!logging || logging.length === 0) {
    return html`<${EmptyPanel} style=${{
      fontSize: FontSize.base,
    }}>No Messages</${EmptyPanel}>`;
  }

  if (logging.length > 1000 && capabilities.downloadFiles) {
    const file = `log.txt`;
    const logContents = logging.map((row) => {
      return `[${row.level.toUpperCase()}] (${new Date(row.created).toISOString()}) ${row.message}`;
    });
    return html`<div style=${{ width: "100%" }}>
      <${DownloadPanel}
        message="There are too many logging entries to render."
        buttonLabel="Download Log File"
        logFile=${logFile}
        fileName=${file}
        fileContents=${logContents.join("\n")}
      />
    </div>`;
  } else {
    return html`
      <table
        class="table table-hover table-sm"
        style=${{
          fontSize: FontSize.small,
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
                    fontSize: FontSize.smaller,
                    color: color(log.level),
                  }}
                ></i>
              </td>
              <td>
                <pre
                  style=${{
                    fontSize: FontSize.smaller,
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
                        fontSize: FontSize.smaller,
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
  }
};

const icon = (level) => {
  const icon = ApplicationIcons.logging[level.toLowerCase()];
  return icon || ApplicationIcons.logging.notset;
};

const color = (level) => {
  const color = ApplicationColors.logging[level.toLowerCase()];
  return color || ApplicationColors.debug;
};
