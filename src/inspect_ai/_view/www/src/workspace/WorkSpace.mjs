import { html } from "htm/preact";
import {
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
} from "preact/hooks";

import { icons } from "../Constants.mjs";
import { EpochFilter } from "./EpochFilter.mjs";
import {
  SortFilter,
  sort,
  kDefaultSort,
  byEpoch,
  bySample,
} from "./SortFilter.mjs";
import { formatTime } from "../utils/Format.mjs";
import { TitleBlock } from "../title/TitleBlock.mjs";
import { AppErrorBoundary } from "../components/AppErrorBoundary.mjs";
import { ErrorPanel } from "../components/ErrorPanel.mjs";
import { SamplesCard } from "../samples/SamplesCard.mjs";
import { LoggingPanel } from "../logging/LoggingPanel.mjs";
import { LoadingScreen } from "../components/LoadingScreen.mjs";
import { ToolButton } from "../components/ToolButton.mjs";
import { TabSet, Tab } from "../components/TabSet.mjs";
import { SampleFilter } from "./SampleFilter.mjs";
import { samplesDescriptor } from "./SamplesDescriptor.mjs";
import { eval_log } from "../../api.mjs";
import { PlanCard } from "../plan/PlanCard.mjs";
import { UsageCard } from "../usage/UsageCard.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { TaskErrorCard } from "./TaskErrorPanel.mjs";

const kEvalTabId = "eval-tab";
const kJsonTabId = "json-tab";
const kLoggingTabId = "logging-tab";
const kInfoTabId = "plan-tab";

export const WorkSpace = (props) => {
  const divRef = useRef();
  const codeRef = useRef();

  // State tracking for the view
  const [state, setState] = useState({
    log: {
      contents: undefined,
      path: undefined,
    },
    logFiltered: undefined,
    status: "loading", //loaded,error
    error: undefined,
    viewState: {
      selectedTab: kEvalTabId,
      openSamples: [],
      filter: {},
      epoch: "all",
      sort: kDefaultSort,
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
      state.log.contents?.samples,
      state.log.contents?.eval?.config?.epochs || 1,
      context
    );
  }, [state.log]);

  const toggleSample = (id) => {
    const idx = state.viewState.openSamples.indexOf(id);
    const viewState = state.viewState;
    if (idx < 0) {
      viewState.openSamples.push(id);
    } else {
      viewState.openSamples.splice(idx, 1);
    }
    setState({ log: state.log, viewState });
  };

  const toggleAllSamples = (showAll) => {
    const viewState = state.viewState;
    if (showAll) {
      viewState.openSamples = state.log.contents.samples.map((sample) => {
        return `${sample.id}-${sample.epoch}` ;
      });
    } else {
      viewState.openSamples = [];
    }
    setState({ log: state.log, viewState });
  };

  // Tabs that are available within the app
  // Include the tab contents as well as any tools that the tab provides
  // when it is displayed
  const tabs = useMemo(() => {
    const resolvedTabs = {};

    // The samples tab
    // Currently only appears when the result is successful
    if (state.log.contents?.status === "success") {
      resolvedTabs.samples = {
        id: kEvalTabId,
        label: "Samples",
        content: () => {
          // Filter the samples based upon the filter state
          const filter = state.viewState.filter;
          const samples = (state.log.contents?.samples || []).filter(
            (sample) => {
              // Filter by epoch if specified
              if (state.viewState.epoch && state.viewState.epoch !== "all") {
                if (state.viewState.epoch !== sample.epoch + "") {
                  return false;
                }
              }

              if (filter.filterFn && filter.value) {
                return filter.filterFn(sample, filter.value);
              } else {
                return true;
              }
            }
          );

          const { sorted, numbering } = sort(
            state.viewState.sort,
            samples,
            sampleDescriptor
          );

          const groupBy = (sort, sampleDescriptor) => {
            // No grouping if there is only one epoch
            if (sampleDescriptor.epochs < 2) {
              return "";
            }

            if (byEpoch(sort) || state.viewState.epoch !== "all") {
              return "epoch";
            } else if (bySample(sort)) {
              return "sample";
            } else {
              return "";
            }
          };

          return html`<${SamplesCard}
            samples="${sorted}"
            toggleSample=${toggleSample}
            openSamples=${state.viewState.openSamples}
            context=${context}
            sampleDescriptor=${sampleDescriptor}
            groupBy=${groupBy(state.viewState.sort, sampleDescriptor)}
            numbering=${numbering}
          />`;
        },
        tools: (state) => {
          const hasEpochs = state.log.contents?.eval?.config?.epochs > 1;
          const tools = [];
          if (hasEpochs) {
            tools.push(
              html`<${EpochFilter}
                epoch=${state.viewState.epoch}
                setEpoch="${setEpoch}"
                epochs=${state.log.contents.eval.config.epochs}
              />`
            );
          }

          tools.push(
            html`<${SampleFilter}
              filter=${state.viewState.filter}
              filterChanged=${filterChanged}
              descriptor=${sampleDescriptor}
            />`
          );

          tools.push(
            html`<${SortFilter}
              sort=${state.viewState.sort}
              setSort=${setSort}
              epochs=${hasEpochs}
            />`
          );

          if (state.viewState.openSamples.length > 0) {
            tools.push(
              html`<${ToolButton}
                name="Close All"
                icon="${icons["expand-all"]}"
                onclick="${hideAll}"
              />`
            );
          }
          if (
            state.viewState.openSamples.length <
            state.log.contents?.samples?.length
          ) {
            tools.push(
              html`<${ToolButton}
                name="Open All"
                icon="${icons["collapse-all"]}"
                onclick="${showAll}"
              />`
            );
          }

          return tools;
        },
      };
    }

    // The info tab
    resolvedTabs.config = {
      id: kInfoTabId,
      label: "Info",
      content: () => {
        const infoCards = [
          html`<${PlanCard} log="${state.log.contents}" context=${context} />`,
          html`<${UsageCard}
            stats=${state.log.contents?.stats}
            context=${context}
          />`,
        ];

        // If there is error or progress, includes those within info
        if (state.log.contents?.status === "error") {
          infoCards.unshift(
            html`<${TaskErrorCard} evalError=${state.log.contents.error} />`
          );
        } else if (state.log.contents?.status === "started") {
          infoCards.unshift(
            html`<${EmptyPanel}>The task is currently running.</${EmptyPanel}>`
          );
        }
        return html` ${infoCards} `;
      },
    };

    // The Logging Messages tab
    resolvedTabs.logging = {
      id: kLoggingTabId,
      label: "Logging",
      content: () => {
        return html`<${LoggingPanel}
          logging=${state.log.contents?.logging}
          context=${context}
        />`;
      },
      tools: (_state) => [],
    };

    // The JSON Tab
    resolvedTabs.json = {
      id: kJsonTabId,
      label: "JSON",
      content: () => {
        return html`<div
          style=${{
            border: "solid 1px var(--bs-border-color)",
            borderRadius: "var(--bs-border-radius)",
            padding: "1rem",
            fontSize: "0.9rem",
          }}
        >
          <pre>
      <code id="task-json-contents" class="sourceCode" ref=${codeRef} style=${{
            whiteSpace: "pre-wrap",
            fontSize: "0.9em",
          }}></code></pre>
        </div>`;
      },
      tools: (_state) => [
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
  }, [state]);

  const setSelectedTab = (currentState, selectedTab) => {
    const viewState = currentState.viewState;
    viewState.selectedTab = selectedTab;
    setState({
      log: currentState.log,
      viewState,
    });
  };

  const showAll = useCallback(
    (e) => {
      toggleAllSamples(true);
    },
    [state]
  );

  const hideAll = useCallback(
    (e) => {
      toggleAllSamples(false);
    },
    [state]
  );

  const filterChanged = useCallback(
    (filter) => {
      const viewState = state.viewState;
      viewState.filter = filter;
      setState({ log: state.log, viewState });
      hideAll();
    },
    [state]
  );

  const setEpoch = useCallback(
    (epoch) => {
      const viewState = state.viewState;
      viewState.epoch = epoch;
      setState({ log: state.log, viewState });
    },
    [state]
  );

  const setSort = useCallback(
    (sort) => {
      const viewState = state.viewState;
      viewState.sort = sort;
      setState({ log: state.log, viewState });
    },
    [state]
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
    [state]
  );

  const selectTab = (event) => {
    const id = event.currentTarget.id;
    setSelectedTab(state, id);
  };

  /**
   *
   * @param {import('../../log.d.ts').EvalLog} log
   */
  const showLog = (log) => {
    if (log.contents) {
      setSelectedTab(state, kEvalTabId);

      divRef.current.scrollTop = 0;
      if (log.contents.samples.length <= 200) {
        codeRef.current.innerHTML = Prism.highlight(
          JSON.stringify(log.contents, null, 2),
          Prism.languages.javascript,
          "javacript"
        );
      } else {
        codeRef.current.innerHTML = JSON.stringify(log.contents, null, 2);
      }
    }
  };

  useEffect(async () => {
    const viewState = state.viewState;
    if (props.logs.files.length > 0) {
      const log = props.logs.files[props.selected];
      if (state.log.path !== log.name) {
        setState({...state, status: "loading"});
        try {
          const logContents = await eval_log(log?.name);
          viewState.openSamples = [];
          viewState.sort = kDefaultSort;
          viewState.filter = {};
          viewState.epoch = "all";

          setState({
            log: { contents: logContents, path: log.name },
            viewState,
          });
        } catch (e) {
          // Show an error
          console.log(e);
          setState({ log: state.log, viewState, status: "error", error: e });
        }
      }
    } else {
      setState({ log: { contents: undefined, path: undefined }, viewState });
    }
  }, [props.logs, props.selected]);


  // Display the log
  useEffect(() => {    
    showLog(state.log);
  }, [state.log]);

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

  return html`<${WorkspaceDisplay}
    divRef=${divRef}
    tabs=${tabs}
    tabTools=${tabTools}
    state=${state}
    fullScreen=${props.fullScreen}
    offcanvas=${props.offcanvas}
    context=${context}
    afterBodyElements=${afterBodyElements}
  />`;
};

const WorkspaceDisplay = ({
  state,
  tabs,
  tabTools,
  selectTab,
  fullScreen,
  offcanvas,
  divRef,
  context,
  afterBodyElements
}) => {
  if (state.status === "loading") {
    return html`<${LoadingScreen} />`;
  } else if (state.status === "error") {    
    return html`<${ErrorPanel}
      title="An error occurred while loading this task."
      error=${state.error}
    />`;
  } else if (state.log.contents === undefined) {
    return html`<${EmptyPanel} />`;
  } else {
    const totalDuration = duration(state.log.contents?.stats);
    const tertiaryTitle = !totalDuration
      ? new Date(state.log.contents?.eval.created).toLocaleString()
      : html`
          ${new Date(state.log.contents?.eval.created).toLocaleString()}
          <span style=${{ color: "var(--bs-secondary)" }}>
            — ${totalDuration}</span
          >
        `;
    const fullScreenClz = fullScreen ? " full-screen" : "";
    const offcanvasClz = offcanvas ? " off-canvas" : "";

    return html`
        <${AppErrorBoundary}>
          <div ref=${divRef} class="workspace${fullScreenClz}${offcanvasClz}" style=${{
      marginTop: "0.5rem",
    }}>
            <${TitleBlock}
              title=${state.log.contents?.eval?.task}
              subtitle=${state.log.contents?.eval?.model}
              tertiaryTitle=${tertiaryTitle}
              log=${state.log.contents}
              metrics=${state.log.contents?.results?.metrics}
              context=${context}
            />
            <div
              class="log-detail"
              style=${{
                borderTop: "solid 1px var(--bs-border-color)",
                padding: "0.5em 1em 1em 1em",
              }}
            >
            <${TabSet} id="log-details" tools="${tabTools}" type="pills" style=${{
      fontSize: "0.8rem",
      flexWrap: "nowrap",
    }}>
              ${Object.keys(tabs).map((key) => {
                const tab = tabs[key];
                return html`<${Tab} id=${tab.id} title="${
                  tab.label
                }" onSelected="${selectTab}" selected=${
                  state.viewState.selectedTab === tab.id
                } style=${{
                  padding: ".3rem 0.3rem .3rem 0.3rem",
                  width: "5em",
                  fontSize: "0.7rem",
                }}>
                  ${tab.content()}
                </${Tab}>`;
              })}
            </${TabSet}>
            </div>
          </div>
          
          ${afterBodyElements}
        </${AppErrorBoundary}>`;
  }
};

const duration = (stats) => {
  if (stats) {
    const start = new Date(stats.started_at);
    const end = new Date(stats.completed_at);
    const durationMs = end.getTime() - start.getTime();
    const durationSec = durationMs / 1000;
    return formatTime(durationSec);
  } else {
    return undefined;
  }
};
