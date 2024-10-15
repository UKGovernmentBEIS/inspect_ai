/// <reference path="../types/prism.d.ts" />
import Prism from "prismjs";
import { html } from "htm/preact";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { TabPanel, TabSet } from "../components/TabSet.mjs";
import { ToolButton } from "../components/ToolButton.mjs";
import { PlanCard } from "../plan/PlanCard.mjs";
import { samplesDescriptor } from "../samples/SamplesDescriptor.mjs";
import { SamplesTab } from "../samples/SamplesTab.mjs";
import { SampleTools } from "../samples/SamplesTools.mjs";
import { kDefaultSort } from "../samples/tools/SortFilter.mjs";
import { UsageCard } from "../usage/UsageCard.mjs";
import { filename } from "../utils/Path.mjs";
import { Navbar } from "../navbar/Navbar.mjs";

import { DownloadPanel } from "../components/DownloadPanel.mjs";
import { TaskErrorCard } from "./TaskErrorPanel.mjs";
import { FontSize } from "../appearance/Fonts.mjs";
import { WarningBand } from "../components/WarningBand.mjs";

const kEvalTabId = "eval-tab";
const kJsonTabId = "json-tab";
const kInfoTabId = "plan-tab";

const kPrismRenderMaxSize = 250000;
const kJsonMaxSize = 10000000;

/**
 * Renders the Main Application
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../Types.mjs").CurrentLog} [props.log] - the current log
 * @param {import("../types/log").Sample} [props.sample] - the current sample (if any)
 * @param {string} props.sampleStatus - whether a sample is loading
 * @param {boolean} props.showToggle - whether to show the toggler
 * @param {() => Promise<void>} props.refreshLog - Whether the application should poll for log changes
 * @param {import("../Types.mjs").Capabilities} props.capabilities - Capabilities of the application host
 * @param {number} props.selectedSampleIndex - the selected sample index
 * @param { (index: number) => void } props.setSelectedSampleIndex - function to selected a sample
 * @param {boolean} props.offcanvas - is this off canvas
 * @returns {import("preact").JSX.Element} The TranscriptView component.
 */
export const WorkSpace = ({
  log: currentLog,
  sample,
  showToggle,
  refreshLog,
  capabilities,
  offcanvas,
  selectedSampleIndex,
  setSelectedSampleIndex,
  sampleStatus,
}) => {
  const divRef = useRef(/** @type {HTMLElement|null} */ (null));
  const codeRef = useRef(/** @type {HTMLElement|null} */ (null));

  // State tracking for the view
  const [currentTaskId, setCurrentTaskId] = useState(
    currentLog?.contents?.eval?.run_id,
  );
  const [selectedTab, setSelectedTab] = useState();

  /**
   * @type {[import("../Types.mjs").ScoreLabel[], function(import("../Types.mjs").ScoreLabel[]): void]}
   */
  const [scores, setScores] = useState([]);

  /**
   * @type {[import("../Types.mjs").ScoreLabel, function(import("../Types.mjs").ScoreLabel): void]}
   */
  const [score, setScore] = useState(undefined);

  /**
   * @type {[import("../samples/SamplesDescriptor.mjs").SamplesDescriptor | undefined, function(import("../samples/SamplesDescriptor.mjs").SamplesDescriptor | undefined): void]}
   */
  const [samplesDesc, setSamplesDesc] = useState(undefined);

  /**
   * @type {[import("../Types.mjs").ScoreFilter, function(import("../Types.mjs").ScoreFilter): void]}
   */
  const [filter, setFilter] = useState({});

  /**
   * @type {[string, function(string): void]}
   */
  const [epoch, setEpoch] = useState("all");

  /**
   * @type {[string, function(string): void]}
   */
  const [sort, setSort] = useState(kDefaultSort);

  /**
   * @type {[boolean, function(boolean): void]}
   */
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
      currentLog.contents &&
      currentLog.contents.eval?.run_id !== currentTaskId
    ) {
      const defaultTab = Object.values(tabs)[0].id;
      setSelectedTab(defaultTab);
      if (divRef.current) {
        divRef.current.scrollTop = 0;
      }
    }
  }, [currentLog, divRef, currentTaskId, setSelectedTab]);

  useEffect(() => {
    // Select the default scorer to use
    const scorer = currentLog?.contents?.results?.scores[0]
      ? {
          name: currentLog.contents.results?.scores[0].name,
          scorer: currentLog.contents.results?.scores[0].scorer,
        }
      : undefined;
    const scorers = (currentLog.contents?.results?.scores || [])
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
  }, [currentLog, setScores, setScore, setEpoch, setFilter, setRenderedCode]);

  useEffect(() => {
    clearSampleTools();
  }, [score]);

  useEffect(() => {
    const sampleDescriptor = samplesDescriptor(
      scores,
      currentLog.contents?.sampleSummaries,
      currentLog.contents?.eval?.config?.epochs || 1,
      context,
      score,
    );
    setSamplesDesc(sampleDescriptor);
  }, [currentLog, score, scores, setSamplesDesc]);

  useEffect(() => {
    setCurrentTaskId(currentLog.contents?.eval?.run_id);
  }, [currentLog]);

  // Tabs that are available within the app
  // Include the tab contents as well as any tools that the tab provides
  // when it is displayed
  const tabs = useMemo(() => {
    const resolvedTabs = {};

    // The samples tab
    // Currently only appears when the result is successful
    if (
      currentLog.contents?.status !== "error" &&
      currentLog.contents?.sampleSummaries
    ) {
      resolvedTabs.samples = {
        id: kEvalTabId,
        scrollable: currentLog.contents?.sampleSummaries?.length === 1,
        label:
          currentLog.contents?.sampleSummaries?.length > 1
            ? "Samples"
            : "Sample",
        content: () => {
          return html` <${SamplesTab}
            task=${currentLog.contents?.eval?.task_id}
            selectedScore=${score}
            sample=${sample}
            sampleLoading=${sampleStatus === "loading"}
            samples=${currentLog.contents?.sampleSummaries}
            selectedSampleIndex=${selectedSampleIndex}
            setSelectedSampleIndex=${setSelectedSampleIndex}
            sampleDescriptor=${samplesDesc}
            filter=${filter}
            sort=${sort}
            epoch=${epoch}
            context=${context}
          />`;
        },
        tools: () => {
          if (currentLog.contents?.status === "started") {
            return html`<${ToolButton}
              name=${html`Refresh`}
              icon="${ApplicationIcons.refresh}"
              onclick="${refreshLog}"
            />`;
          }

          // Don't show tools if there is a sample sample
          if (currentLog.contents?.sampleSummaries?.length <= 1) {
            return "";
          }
          return html`<${SampleTools}
            epoch=${epoch}
            epochs=${currentLog.contents?.eval?.config?.epochs}
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
        const infoCards = [];
        infoCards.push([
          html`<${PlanCard} log="${currentLog.contents}" context=${context} />`,
        ]);

        if (currentLog.contents?.status !== "started") {
          infoCards.push(
            html`<${UsageCard}
              stats=${currentLog.contents?.stats}
              context=${context}
            />`,
          );
        }

        // If there is error or progress, includes those within info
        if (
          currentLog.contents?.status === "error" &&
          currentLog.contents?.error
        ) {
          infoCards.unshift(
            html`<${TaskErrorCard} evalError=${currentLog.contents.error} />`,
          );
        }

        const warnings = [];
        if (
          !currentLog.contents?.sampleSummaries &&
          currentLog.contents?.eval?.dataset?.samples > 0 &&
          currentLog.contents?.status !== "error"
        ) {
          warnings.push(
            html`<${WarningBand}
              message="Unable to display samples (this evaluation log may be too large)."
            />`,
          );
        }

        return html` <div style=${{ width: "100%" }}>
          ${warnings}
          <div style=${{ padding: "0.5em 1em 0 1em", width: "100%" }}>
            ${infoCards}
          </div>
        </div>`;
      },
    };

    // The JSON Tab
    resolvedTabs.json = {
      id: kJsonTabId,
      label: "JSON",
      scrollable: true,
      content: () => {
        const renderedContent = [];
        if (
          currentLog.raw.length > kJsonMaxSize &&
          capabilities.downloadFiles
        ) {
          // This JSON file is so large we can't really productively render it
          // we should instead just provide a DL link
          const file = `${filename(currentLog.name)}.json`;
          renderedContent.push(
            html`<${DownloadPanel}
              message="Log file raw JSON is too large to render."
              buttonLabel="Download JSON File"
              logFile=${currentLog.name}
              fileName=${file}
              fileContents=${currentLog.raw}
            />`,
          );
        } else {
          if (codeRef.current && !renderedCode) {
            if (currentLog.raw.length < kPrismRenderMaxSize) {
              codeRef.current.innerHTML = Prism.highlight(
                currentLog.raw,
                Prism.languages.javascript,
                "javacript",
              );
            } else {
              const textNode = document.createTextNode(currentLog.raw);
              codeRef.current.innerText = "";
              codeRef.current.appendChild(textNode);
            }

            setRenderedCode(true);
          }
          renderedContent.push(
            html`<pre>
            <code id="task-json-contents" class="sourceCode" ref=${codeRef} style=${{
              fontSize: FontSize.small,
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
            fontSize: FontSize.small,
            width: "100%",
          }}
        >
          ${renderedContent}
        </div>`;
      },
      tools: () => {
        if (currentLog.raw.length > kJsonMaxSize) {
          return [];
        } else {
          return [
            html`<${ToolButton}
              name=${html`<span class="task-btn-copy-content">Copy JSON</span>`}
              icon="${ApplicationIcons.copy}"
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
    sample,
    currentLog,
    filter,
    setFilter,
    epoch,
    setEpoch,
    sort,
    setSort,
    renderedCode,
    setRenderedCode,
    selectedSampleIndex,
    sampleStatus,
  ]);

  const copyFeedback = useCallback(
    (e) => {
      const textEl = e.currentTarget.querySelector(".task-btn-copy-content");
      const iconEl = e.currentTarget.querySelector("i.bi");
      if (textEl) {
        const oldText = textEl.innerText;
        const oldIconClz = iconEl.className;
        textEl.innerText = "Copied!";
        iconEl.className = `${ApplicationIcons.confirm}`;
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
    log=${currentLog}
    showToggle=${showToggle}
    selectedTab=${selectedTab}
    offcanvas=${offcanvas}
    setSelectedTab=${setSelectedTab}
    afterBodyElements=${afterBodyElements}
  />`;
};

const WorkspaceDisplay = ({
  log,
  showToggle,
  selectedTab,
  tabs,
  tabTools,
  setSelectedTab,
  divRef,
  afterBodyElements,
  offcanvas,
}) => {
  if (log.contents === undefined) {
    return html`<${EmptyPanel} />`;
  } else {
    return html`
    
    <${Navbar}
      file=${log.name}
      showToggle=${showToggle}
      log=${log.contents}
      offcanvas=${offcanvas}
    />    
    <div ref=${divRef} class="workspace" style=${{
      paddingTop: "0rem",
      overflowY: "hidden",
    }}>
            <div
              class="log-detail"
              style=${{
                padding: "0",
                flex: 1,
                display: "flex",
                flexDirection: "column",
                overflowY: "hidden",
              }}
            >
            <${TabSet} id="log-details" tools="${tabTools}" type="pills" styles=${{
              tabSet: {
                fontSize: FontSize.smaller,
                flexWrap: "nowrap",
                padding: "0.5em 1em 0.5em 1em",
                borderBottom: "solid 1px var(--bs-border-color)",
                background: "var(--bs-light)",
              },
              tabBody: { flex: "1", overflowY: "hidden", display: "flex" },
              tabs: {
                padding: ".3rem 0.3rem .3rem 0.3rem",
                width: "5rem",
                fontSize: FontSize.smaller,
                textTransform: "uppercase",
                borderRadius: "var(--bs-border-radius)",
                fontWeight: 600,
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
