import { html } from "htm/preact";
import {
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
} from "preact/hooks";

import { icons } from "../Constants.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { TabSet, TabPanel } from "../components/TabSet.mjs";
import { ToolButton } from "../components/ToolButton.mjs";
import { LoggingPanel } from "../logging/LoggingPanel.mjs";
import { PlanCard } from "../plan/PlanCard.mjs";
import { samplesDescriptor } from "../samples/SamplesDescriptor.mjs";
import { SamplesTab } from "../samples/SamplesTab.mjs";
import { SampleTools } from "../samples/SamplesTools.mjs";
import { kDefaultSort } from "../samples/tools/SortFilter.mjs";
import { TitleBlock } from "../title/TitleBlock.mjs";
import { UsageCard } from "../usage/UsageCard.mjs";

import { TaskErrorCard } from "./TaskErrorPanel.mjs";

const kEvalTabId = "eval-tab";
const kJsonTabId = "json-tab";
const kLoggingTabId = "logging-tab";
const kInfoTabId = "plan-tab";

const kPrismRenderMaxSize = 250000;

export const WorkSpace = (props) => {
  const divRef = useRef();
  const codeRef = useRef();

  const workspaceLog = props.log;

  const [currentTaskId, setCurrentTaskId] = useState(
    workspaceLog?.contents?.eval?.run_id,
  );

  // State tracking for the view
  const [state, setState] = useState({
    logFiltered: undefined,
    viewState: {
      selectedTab: kEvalTabId,
      openSamples: [],
      filter: {},
      epoch: "all",
      sort: kDefaultSort,
      renderedCode: false,
    },
  });

  // Context is shared with most/all components and
  // allows for global information to pass between components
  const afterBodyElements = [];
  const context = {
    afterBody: (el) => {
      afterBodyElements.push(el);
    },
  };

  const sampleDescriptor = useMemo(() => {
    return samplesDescriptor(
      workspaceLog.contents?.samples,
      workspaceLog.contents?.eval?.config?.epochs || 1,
      context,
    );
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
            task=${workspaceLog.contents?.eval?.task}
            model=${workspaceLog.contents?.eval?.model}
            samples=${workspaceLog.contents?.samples}
            sampleDescriptor=${sampleDescriptor}
            filter=${state.viewState.filter}
            sort=${state.viewState.sort}
            epoch=${state.viewState.epoch}
            context=${context}
          />`;
        },
        tools: (state) => {
          // Don't show tools if there is a sample sample
          if (workspaceLog.contents?.samples?.length <= 1) {
            return "";
          }
          return html`<${SampleTools}
            epoch=${state.viewState.epoch}
            epochs=${workspaceLog.contents?.eval?.config?.epochs}
            setEpoch=${setEpoch}
            filter=${state.viewState.filter}
            filterChanged=${filterChanged}
            sort=${state.viewState.sort}
            setSort=${setSort}
            sampleDescriptor=${sampleDescriptor}
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
          logging=${workspaceLog.contents?.logging}
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
        if (codeRef.current && !state.viewState.renderedCode) {
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

          const viewState = state.viewState;
          viewState.renderedCode = true;
          setState({ viewState });
        }

        // note that we'e rendered
        return html` <div
          style=${{
            padding: "1rem",
            fontSize: "0.9rem",
          }}
        >
          <pre>
            <code id="task-json-contents" class="sourceCode" ref=${codeRef} style=${{
            fontSize: "0.9em",
            whiteSpace: "pre-wrap",
            wordWrap: "anywhere",
          }}>
            </code>
          </pre>
        </div>`;
      },
      tools: () => [
        html`<${ToolButton}
          name=${html`<span class="task-btn-copy-content">Copy JSON</span>`}
          icon="${icons.copy}"
          classes="task-btn-json-copy clipboard-button"
          data-clipboard-target="#task-json-contents"
          onclick="${copyFeedback}"
        />`,
      ],
    };

    return resolvedTabs;
  }, [state, workspaceLog]);

  const setSelectedTab = (currentState, selectedTab) => {
    const viewState = currentState.viewState;
    viewState.selectedTab = selectedTab;
    setState({ viewState });
  };

  const filterChanged = useCallback(
    (filter) => {
      const viewState = state.viewState;
      viewState.filter = filter;
      setState({ viewState });
    },
    [state, setState],
  );

  const setEpoch = useCallback(
    (epoch) => {
      const viewState = state.viewState;
      viewState.epoch = epoch;
      setState({ viewState });
    },
    [state],
  );

  const setSort = useCallback(
    (sort) => {
      const viewState = state.viewState;
      viewState.sort = sort;
      setState({ viewState });
    },
    [state],
  );

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
    [state],
  );

  // Display the log
  useEffect(() => {
    if (workspaceLog.contents && workspaceLog.eval?.run_id !== currentTaskId) {
      const defaultTab =
        workspaceLog.contents?.status !== "error" ? kEvalTabId : kInfoTabId;
      setSelectedTab(state, defaultTab);
      if (divRef.current) {
        divRef.current.scrollTop = 0;
      }
    }

    // Reset state
    const newState = {
      openSamples: [],
      filter: {},
      epoch: "all",
      sort: kDefaultSort,
      renderedCode: false,
    };

    setState({ viewState: { ...state.viewState, ...newState } });
  }, [workspaceLog, divRef, currentTaskId]);

  useEffect(() => {
    setCurrentTaskId(workspaceLog.contents?.eval?.run_id);
  }, [workspaceLog]);

  // Compute the tools for this tab
  const tabTools = Object.keys(tabs)
    .map((key) => {
      const tab = tabs[key];
      return tab;
    })
    .filter((tab) => {
      return tab.id === state.viewState.selectedTab;
    })
    .map((tab) => {
      if (tab.tools) {
        const tools = tab.tools(state);
        return tools;
      } else {
        return "";
      }
    });

  const selectTab = (event) => {
    const id = event.currentTarget.id;
    setSelectedTab(state, id);
  };

  return html`<${WorkspaceDisplay}
    divRef=${divRef}
    tabs=${tabs}
    tabTools=${tabTools}
    log=${workspaceLog}
    selectedTab=${state.viewState.selectedTab}
    fullScreen=${props.fullScreen}
    offcanvas=${props.offcanvas}
    context=${context}
    selectTab=${selectTab}
    afterBodyElements=${afterBodyElements}
  />`;
};

const WorkspaceDisplay = ({
  log,
  selectedTab,
  tabs,
  tabTools,
  selectTab,
  fullScreen,
  offcanvas,
  divRef,
  context,
  afterBodyElements,
}) => {
  if (log.contents === undefined) {
    return html`<${EmptyPanel} />`;
  } else {
    const fullScreenClz = fullScreen ? " full-screen" : "";
    const offcanvasClz = offcanvas ? " off-canvas" : "";

    return html`<div ref=${divRef} class="workspace${fullScreenClz}${offcanvasClz}" style=${{
      paddingTop: "0rem",
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
                onSelected="${selectTab}"
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
