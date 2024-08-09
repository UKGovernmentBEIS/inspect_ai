import Prism from "prismjs";
import { html } from "htm/preact";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "preact/hooks";

import { icons } from "../Constants.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { TabPanel, TabSet } from "../components/TabSet.mjs";
import { ToolButton } from "../components/ToolButton.mjs";
import { LoggingPanel } from "../logging/LoggingPanel.mjs";
import { PlanCard } from "../plan/PlanCard.mjs";
import { samplesDescriptor } from "../samples/SamplesDescriptor.mjs";
import { SamplesTab } from "../samples/SamplesTab.mjs";
import { SampleTools } from "../samples/SamplesTools.mjs";
import { kDefaultSort } from "../samples/tools/SortFilter.mjs";
import { TitleBlock } from "../title/TitleBlock.mjs";
import { UsageCard } from "../usage/UsageCard.mjs";
import { filename } from "../utils/Path.mjs";

import { DownloadPanel } from "../components/DownloadPanel.mjs";
import { TaskErrorCard } from "./TaskErrorPanel.mjs";

const kEvalTabId = "eval-tab";
const kJsonTabId = "json-tab";
const kLoggingTabId = "logging-tab";
const kInfoTabId = "plan-tab";

const kPrismRenderMaxSize = 250000;
const kJsonMaxSize = 10000000;

export const WorkSpace = (props) => {
  const divRef = useRef();
  const codeRef = useRef();

  // alias the log for the workspace
  const workspaceLog = props.log;

  // State tracking for the view
  const [currentTaskId, setCurrentTaskId] = useState(
    workspaceLog?.contents?.eval?.run_id,
  );
  const [selectedTab, setSelectedTab] = useState(kEvalTabId);
  const [scores, setScores] = useState([]);
  const [score, setScore] = useState(undefined);
  const [samplesDesc, setSamplesDesc] = useState(undefined);
  const [filter, setFilter] = useState({});
  const [epoch, setEpoch] = useState("all");
  const [sort, setSort] = useState(kDefaultSort);
  const [renderedCode, setRenderedCode] = useState(false);

  // Context is shared with most/all components and
  // allows for global information to pass between components
  const afterBodyElements = [];
  const context = {
    afterBody: (el) => {
      afterBodyElements.push(el);
    },
  };

  const clearSampleTools = useCallback(() => {
    setEpoch("all");
    setFilter({});
    setSort(kDefaultSort);
  }, [setEpoch, setFilter, setSort]);

  // Display the log
  useEffect(() => {
    if (
      workspaceLog.contents &&
      workspaceLog.contents.eval?.run_id !== currentTaskId
    ) {
      const defaultTab =
        workspaceLog.contents?.status !== "error" ? kEvalTabId : kInfoTabId;
      setSelectedTab(defaultTab);
      if (divRef.current) {
        divRef.current.scrollTop = 0;
      }
    }
  }, [workspaceLog, divRef, currentTaskId, setSelectedTab]);

  useEffect(() => {
    // Select the default scorer to use
    const scorer = workspaceLog?.contents?.results?.scores[0]
      ? {
          name: workspaceLog.contents.results.scores[0].name,
          scorer: workspaceLog.contents.results.scores[0].scorer,
        }
      : undefined;
    const scorers = (workspaceLog.contents?.results?.scores || [])
      .map((score) => {
        return {
          name: score.name,
          scorer: score.scorer,
        };
      })
      .reduce((accum, scorer) => {
        if (
          !accum.find((sc) => {
            return scorer.scorer === sc.scorer && scorer.name === sc.name;
          })
        ) {
          accum.push(scorer);
        }
        return accum;
      }, []);

    // Reset state
    setScores(scorers);
    setScore(scorer);
    clearSampleTools();
    setRenderedCode(false);
  }, [workspaceLog, setScores, setScore, setEpoch, setFilter, setRenderedCode]);

  useEffect(() => {
    clearSampleTools();
  }, [score]);

  useEffect(() => {
    const sampleDescriptor = samplesDescriptor(
      score,
      scores,
      workspaceLog.contents?.samples,
      workspaceLog.contents?.eval?.config?.epochs || 1,
      context,
    );
    setSamplesDesc(sampleDescriptor);
  }, [workspaceLog, score, scores, setSamplesDesc]);

  useEffect(() => {
    setCurrentTaskId(workspaceLog.contents?.eval?.run_id);
  }, [workspaceLog]);

  // Tabs that are available within the app
  // Include the tab contents as well as any tools that the tab provides
  // when it is displayed
  const tabs = useMemo(() => {
    const resolvedTabs = {};

    // The samples tab
    // Currently only appears when the result is successful
    if (workspaceLog.contents?.status !== "error") {
      resolvedTabs.samples = {
        id: kEvalTabId,
        scrollable: workspaceLog.contents?.samples?.length === 1,
        label:
          workspaceLog.contents?.samples?.length > 1 ? "Samples" : "Sample",
        content: () => {
          return html` <${SamplesTab}
            task=${workspaceLog.contents?.eval?.task_id}
            model=${workspaceLog.contents?.eval?.model}
            selectedScore=${score}
            setSelectedScore=${setScore}
            samples=${workspaceLog.contents?.samples}
            sampleDescriptor=${samplesDesc}
            filter=${filter}
            sort=${sort}
            epoch=${epoch}
            context=${context}
          />`;
        },
        tools: () => {
          // Don't show tools if there is a sample sample
          if (workspaceLog.contents?.samples?.length <= 1) {
            return "";
          }
          return html`<${SampleTools}
            epoch=${epoch}
            epochs=${workspaceLog.contents?.eval?.config?.epochs}
            setEpoch=${setEpoch}
            filter=${filter}
            filterChanged=${setFilter}
            sort=${sort}
            setSort=${setSort}
            score=${score}
            setScore=${setScore}
            scores=${scores}
            sampleDescriptor=${samplesDesc}
          />`;
        },
      };
    }

    // The info tab
    resolvedTabs.config = {
      id: kInfoTabId,
      label: "Info",
      scrollable: true,
      content: () => {
        const infoCards = [
          html`<${PlanCard}
            log="${workspaceLog.contents}"
            context=${context}
          />`,
        ];

        if (workspaceLog.contents?.status !== "started") {
          infoCards.push(
            html`<${UsageCard}
              stats=${workspaceLog.contents?.stats}
              context=${context}
            />`,
          );
        }

        // If there is error or progress, includes those within info
        if (workspaceLog.contents?.status === "error") {
          infoCards.unshift(
            html`<${TaskErrorCard} evalError=${workspaceLog.contents.error} />`,
          );
        }
        return html`<div style=${{ padding: "0.5em 1em 0 1em", width: "100%" }}>
          ${infoCards}
        </div>`;
      },
    };

    // The Logging Messages tab
    resolvedTabs.logging = {
      id: kLoggingTabId,
      label: "Logging",
      scrollable: true,
      content: () => {
        return html`<${LoggingPanel}
          logFile=${workspaceLog.name}
          logging=${workspaceLog.contents?.logging}
          capabilities=${props.capabilities}
          context=${context}
        />`;
      },
      tools: () => [],
    };

    // The JSON Tab
    resolvedTabs.json = {
      id: kJsonTabId,
      label: "JSON",
      scrollable: true,
      content: () => {
        const renderedContent = [];
        if (
          workspaceLog.raw.length > kJsonMaxSize &&
          props.capabilities.downloadFiles
        ) {
          // This JSON file is so large we can't really productively render it
          // we should instead just provide a DL link
          const file = `${filename(workspaceLog.name)}.json`;
          renderedContent.push(
            html`<${DownloadPanel}
              message="Log file raw JSON is too large to render."
              buttonLabel="Download JSON File"
              logFile=${workspaceLog.name}
              fileName=${file}
              fileContents=${workspaceLog.raw}
            />`,
          );
        } else {
          if (codeRef.current && !renderedCode) {
            if (workspaceLog.raw.length < kPrismRenderMaxSize) {
              codeRef.current.innerHTML = Prism.highlight(
                workspaceLog.raw,
                Prism.languages.javascript,
                "javacript",
              );
            } else {
              const textNode = document.createTextNode(workspaceLog.raw);
              codeRef.current.innerText = "";
              codeRef.current.appendChild(textNode);
            }

            setRenderedCode(true);
          }
          renderedContent.push(
            html`<pre>
            <code id="task-json-contents" class="sourceCode" ref=${codeRef} style=${{
              fontSize: "0.9em",
              whiteSpace: "pre-wrap",
              wordWrap: "anywhere",
            }}>
            </code>
          </pre>`,
          );
        }

        // note that we'e rendered
        return html` <div
          style=${{
            padding: "1rem",
            fontSize: "0.9rem",
            width: "100%",
          }}
        >
          ${renderedContent}
        </div>`;
      },
      tools: () => {
        if (workspaceLog.raw.length > kJsonMaxSize) {
          return [];
        } else {
          return [
            html`<${ToolButton}
              name=${html`<span class="task-btn-copy-content">Copy JSON</span>`}
              icon="${icons.copy}"
              classes="task-btn-json-copy clipboard-button"
              data-clipboard-target="#task-json-contents"
              onclick="${copyFeedback}"
            />`,
          ];
        }
      },
    };

    return resolvedTabs;
  }, [
    samplesDesc,
    workspaceLog,
    filter,
    setFilter,
    epoch,
    setEpoch,
    sort,
    setSort,
    renderedCode,
    setRenderedCode,
  ]);

  const copyFeedback = useCallback(
    (e) => {
      const textEl = e.currentTarget.querySelector(".task-btn-copy-content");
      const iconEl = e.currentTarget.querySelector("i.bi");
      if (textEl) {
        const oldText = textEl.innerText;
        const oldIconClz = iconEl.className;
        textEl.innerText = "Copied!";
        iconEl.className = `${icons.confirm}`;
        setTimeout(() => {
          window.getSelection().removeAllRanges();
        }, 50);
        setTimeout(() => {
          textEl.innerText = oldText;
          iconEl.className = oldIconClz;
        }, 1250);
      }
    },
    [renderedCode],
  );

  // Compute the tools for this tab
  const tabTools = Object.keys(tabs)
    .map((key) => {
      const tab = tabs[key];
      return tab;
    })
    .filter((tab) => {
      return tab.id === selectedTab;
    })
    .map((tab) => {
      if (tab.tools) {
        const tools = tab.tools();
        return tools;
      } else {
        return "";
      }
    });

  return html`<${WorkspaceDisplay}
    divRef=${divRef}
    tabs=${tabs}
    tabTools=${tabTools}
    log=${workspaceLog}
    selectedTab=${selectedTab}
    fullScreen=${props.fullScreen}
    offcanvas=${props.offcanvas}
    context=${context}
    setSelectedTab=${setSelectedTab}
    afterBodyElements=${afterBodyElements}
  />`;
};

const WorkspaceDisplay = ({
  log,
  selectedTab,
  tabs,
  tabTools,
  setSelectedTab,
  divRef,
  context,
  afterBodyElements,
}) => {
  if (log.contents === undefined) {
    return html`<${EmptyPanel} />`;
  } else {
    return html`<div ref=${divRef} class="workspace" style=${{
      paddingTop: "0rem",
      overflowY: "hidden",
    }}>
            <${TitleBlock}
              created=${log.contents?.eval.created}
              stats=${log.contents?.stats}
              log=${log.contents}
              context=${context}
              status=${log.contents?.status}
            />
            <div
              class="log-detail"
              style=${{
                borderTop: "solid 1px var(--bs-border-color)",
                padding: "0",
                flex: 1,
                display: "flex",
                flexDirection: "column",
                overflowY: "hidden",
              }}
            >
            <${TabSet} id="log-details" tools="${tabTools}" type="pills" styles=${{
              tabSet: {
                fontSize: "0.8rem",
                flexWrap: "nowrap",
                padding: "0.5em 1em 0.5em 1em",
                borderBottom: "solid 1px var(--bs-border-color)",
              },
              tabBody: { flex: "1", overflowY: "hidden", display: "flex" },
              tabs: {
                padding: ".3rem 0.3rem .3rem 0.3rem",
                width: "5em",
                fontSize: "0.7rem",
              },
            }} >
              ${Object.keys(tabs).map((key) => {
                const tab = tabs[key];
                return html`<${TabPanel}
                id=${tab.id}
                title="${tab.label}"
                onSelected=${(e) => {
                  const id = e.currentTarget.id;
                  setSelectedTab(id);
                }}
                selected=${selectedTab === tab.id}
                scrollable=${!!tab.scrollable}>
                  ${tab.content()}
                </${TabPanel}>`;
              })}
            </${TabSet}>
            </div>
          </div>
          ${afterBodyElements}`;
  }
};
