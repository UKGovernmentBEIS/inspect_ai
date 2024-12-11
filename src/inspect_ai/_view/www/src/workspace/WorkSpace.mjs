/// <reference path="../types/prism.d.ts" />
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
import { SamplesTab } from "../samples/SamplesTab.mjs";
import { JsonTab } from "../json/JsonTab.mjs";
import { SampleTools } from "../samples/SamplesTools.mjs";
import { UsageCard } from "../usage/UsageCard.mjs";
import { Navbar } from "../navbar/Navbar.mjs";

import { TaskErrorCard } from "./TaskErrorPanel.mjs";
import { FontSize } from "../appearance/Fonts.mjs";
import { MessageBand } from "../components/MessageBand.mjs";
import {
  kEvalWorkspaceTabId,
  kInfoWorkspaceTabId,
  kJsonWorkspaceTabId,
} from "../constants.mjs";
import { debounce } from "../utils/sync.mjs";

/**
 * Renders the Main Application
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} [props.task_id] - The task id
 * @param {string} [props.logFileName] - The logFileName name
 * @param {string} [props.evalError] - Error message for this eval
 * @param {string} [props.evalStatus] - status
 * @param {number} [props.evalVersion] - the eval version
 * @param {import("../types/log").EvalSpec} [props.evalSpec] - The EvalSpec for this eval
 * @param {import("../types/log").EvalPlan} [props.evalPlan] - The EvalPlan for this eval
 * @param {import("../types/log").EvalStats} [props.evalStats] - The EvalStats for this eval
 * @param {import("../types/log").EvalResults} [props.evalResults] - The EvalResults for this eval
 * @param {import("../Types.mjs").CurrentLog} [props.log] - the current log
 * @param {import("../api/Types.mjs").SampleSummary[]} [props.samples] - the samples
 * @param {import("../Types.mjs").SampleMode} props.sampleMode - the mode for displaying samples
 * @param {string} props.groupBy - what to group by
 * @param {string} props.groupByOrder - the grouping order
 * @param {import("../types/log").Sample} [props.selectedSample] - the current sample (if any)
 * @param {string} props.sampleStatus - whether a sample is loading
 * @param {Error} [props.sampleError] - sample error
 * @param {boolean} props.showToggle - whether to show the toggler
 * @param {() => Promise<void>} props.refreshLog - Whether the application should poll for log changes
 * @param {import("../Types.mjs").Capabilities} props.capabilities - Capabilities of the application host
 * @param {number} props.selectedSampleIndex - the selected sample index
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor | undefined} props.samplesDescriptor - the samples descriptor
 * @param {(index: number) => void} props.setSelectedSampleIndex - function to selected a sample
 * @param {string} props.selectedSampleTab - the selected sample tab
 * @param {(tab: string) => void} props.setSelectedSampleTab - the function to select a sample tab
 * @param {string} props.sort - the current sort
 * @param {(sort: string) => void} props.setSort - set the current sort
 * @param {number} [props.epochs] - the number of epochs
 * @param {string} props.epoch - the current epoch
 * @param {boolean} props.showingSampleDialog - Whether the sample dialog is showing
 * @param {(showing: boolean) => void} props.setShowingSampleDialog - Call to show the sample dialog
 * @param {(epoch: string) => void} props.setEpoch - set the current epoch
 * @param {import("../Types.mjs").ScoreFilter} props.filter - the current filter
 * @param {(epoch: import("../Types.mjs").ScoreFilter) => void } props.setFilter - set the current filter
 * @param {import("../Types.mjs").ScoreLabel} props.score - The current selected scorer
 * @param {(score: import("../Types.mjs").ScoreLabel) => void} props.setScore - Set the current selected scorer
 * @param {import("../Types.mjs").ScoreLabel[]} props.scores - The current selected scorer
 * @param {boolean} props.offcanvas - is this off canvas
 * @param {string} props.selectedTab - The selected tab id
 * @param {(id: string) => void} props.setSelectedTab - function to update the selected tab
 * @param {import("preact/hooks").MutableRef<number>} props.sampleScrollPositionRef - The initial scroll position for the sample
 * @param {(position: number) => void} props.setSampleScrollPosition - Set the most recent scroll position for this element
 * @param {import("preact/hooks").MutableRef<number>} props.workspaceTabScrollPositionRef - The initial scroll position for the workspace tabs
 * @param {(tab: string, position: number) => void} props.setWorkspaceTabScrollPosition - The initial scroll position for the workspace tabs
 * @returns {import("preact").JSX.Element | string} The Workspace component.
 */
export const WorkSpace = ({
  task_id,
  evalStatus,
  logFileName,
  evalError,
  evalSpec,
  evalVersion,
  evalPlan,
  evalStats,
  evalResults,
  samples,
  sampleMode,
  selectedSample,
  groupBy,
  groupByOrder,
  showToggle,
  refreshLog,
  capabilities,
  offcanvas,
  samplesDescriptor,
  selectedSampleIndex,
  setSelectedSampleIndex,
  showingSampleDialog,
  setShowingSampleDialog,
  selectedSampleTab,
  setSelectedSampleTab,
  sampleStatus,
  sampleError,
  sort,
  setSort,
  epochs,
  epoch,
  setEpoch,
  filter,
  setFilter,
  score,
  setScore,
  scores,
  selectedTab,
  setSelectedTab,
  sampleScrollPositionRef,
  setSampleScrollPosition,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition,
}) => {
  const divRef = useRef(/** @type {HTMLElement|null} */ (null));

  if (!evalSpec) {
    return "";
  }

  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    setHidden(false);
  }, [logFileName]);

  // Display the log
  useEffect(() => {
    if (divRef.current) {
      divRef.current.scrollTop = 0;
    }
  }, [divRef, task_id]);

  const resolvedTabs = useMemo(() => {
    // Tabs that are available within the app
    // Include the tab contents as well as any tools that the tab provides
    // when it is displayed
    const resolvedTabs = {};

    // The samples tab
    // Currently only appears when the result is successful
    if (evalStatus !== "error" && sampleMode !== "none") {
      resolvedTabs.samples = {
        id: kEvalWorkspaceTabId,
        scrollable: samples.length === 1,
        label: samples?.length > 1 ? "Samples" : "Sample",
        content: () => {
          return html` <${SamplesTab}
            task_id=${task_id}
            selectedScore=${score}
            sample=${selectedSample}
            sampleStatus=${sampleStatus}
            sampleError=${sampleError}
            showingSampleDialog=${showingSampleDialog}
            setShowingSampleDialog=${setShowingSampleDialog}
            samples=${samples}
            sampleMode=${sampleMode}
            groupBy=${groupBy}
            groupByOrder=${groupByOrder}
            selectedSampleIndex=${selectedSampleIndex}
            setSelectedSampleIndex=${setSelectedSampleIndex}
            sampleDescriptor=${samplesDescriptor}
            selectedSampleTab=${selectedSampleTab}
            setSelectedSampleTab=${setSelectedSampleTab}
            filter=${filter}
            sort=${sort}
            epoch=${epoch}
            sampleScrollPositionRef=${sampleScrollPositionRef}
            setSampleScrollPosition=${setSampleScrollPosition}
          />`;
        },
        tools: () => {
          // Don't show tools if there is a single sample
          if (sampleMode === "single") {
            return "";
          }
          const sampleTools = [
            html`<${SampleTools}
              epoch=${epoch}
              epochs=${epochs}
              setEpoch=${setEpoch}
              filter=${filter}
              filterChanged=${setFilter}
              sort=${sort}
              setSort=${setSort}
              score=${score}
              setScore=${setScore}
              scores=${scores}
              sampleDescriptor=${samplesDescriptor}
            />`,
          ];
          if (evalStatus === "started") {
            sampleTools.push(
              html`<${ToolButton}
                name=${html`Refresh`}
                icon="${ApplicationIcons.refresh}"
                onclick="${refreshLog}"
              />`,
            );
          }

          return sampleTools;
        },
      };
    }

    // The info tab
    resolvedTabs.config = {
      id: kInfoWorkspaceTabId,
      label: "Info",
      scrollable: true,
      content: () => {
        const infoCards = [];
        infoCards.push([
          html`<${PlanCard}
            evalSpec=${evalSpec}
            evalPlan=${evalPlan}
            scores=${evalResults?.scores}
          />`,
        ]);

        if (evalStatus !== "started") {
          infoCards.push(html`<${UsageCard} stats=${evalStats} />`);
        }

        // If there is error or progress, includes those within info
        if (evalStatus === "error" && evalError) {
          infoCards.unshift(html`<${TaskErrorCard} evalError=${evalError} />`);
        }

        const warnings = [];
        if (
          (!samples || samples.length === 0) &&
          evalSpec?.dataset?.samples > 0 &&
          evalStatus === "success"
        ) {
          warnings.push(
            html`<${MessageBand}
              message="Unable to display samples (this evaluation log may be too large)."
              hidden=${hidden}
              setHidden=${setHidden}
              type="warning"
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
      id: kJsonWorkspaceTabId,
      label: "JSON",
      scrollable: true,
      content: () => {
        const evalHeader = {
          version: evalVersion,
          status: evalStatus,
          eval: evalSpec,
          plan: evalPlan,
          error: evalError,
          results: evalResults,
          stats: evalStats,
        };
        const json = JSON.stringify(evalHeader, null, 2);
        return html`<${JsonTab}
          logFileName=${logFileName}
          json=${json}
          capabilities=${capabilities}
          selected=${selectedTab === kJsonWorkspaceTabId}
        />`;
      },
      tools: () => {
        return [
          html`<${ToolButton}
            name=${html`<span class="task-btn-copy-content">Copy JSON</span>`}
            icon="${ApplicationIcons.copy}"
            classes="task-btn-json-copy clipboard-button"
            data-clipboard-target="#task-json-contents"
            onclick="${copyFeedback}"
          />`,
        ];
      },
    };

    const copyFeedback = (e) => {
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
    };

    return resolvedTabs;
  }, [
    evalStatus,
    sampleMode,
    samples,
    task_id,
    score,
    selectedSample,
    sampleStatus,
    sampleError,
    showingSampleDialog,
    setShowingSampleDialog,
    groupBy,
    groupByOrder,
    selectedSampleIndex,
    setSelectedSampleIndex,
    samplesDescriptor,
    selectedSampleTab,
    setSelectedSampleTab,
    filter,
    sort,
    epoch,
    sampleScrollPositionRef,
    setSampleScrollPosition,
    epochs,
    setEpoch,
    setFilter,
    setSort,
    setScore,
    scores,
    evalSpec,
    evalPlan,
    evalResults,
    evalStats,
    evalError,
    logFileName,
    capabilities,
    selectedTab,
    setHidden,
    hidden,
  ]);

  return html`<${WorkspaceDisplay}
    logFileName=${logFileName}
    divRef=${divRef}
    evalSpec=${evalSpec}
    evalPlan=${evalPlan}
    evalResults=${evalResults}
    evalStats=${evalStats}
    samples=${samples}
    status=${evalStatus}
    tabs=${resolvedTabs}
    selectedTab=${selectedTab}
    showToggle=${showToggle}
    offcanvas=${offcanvas}
    setSelectedTab=${setSelectedTab}
    workspaceTabScrollPositionRef=${workspaceTabScrollPositionRef}
    setWorkspaceTabScrollPosition=${setWorkspaceTabScrollPosition}
  />`;
};

const WorkspaceDisplay = ({
  logFileName,
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  status,
  showToggle,
  selectedTab,
  tabs,
  setSelectedTab,
  divRef,
  offcanvas,
  workspaceTabScrollPositionRef,
  setWorkspaceTabScrollPosition,
}) => {
  if (evalSpec === undefined) {
    return html`<${EmptyPanel} />`;
  } else {
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

    const onScroll = useCallback(
      debounce((id, position) => {
        setWorkspaceTabScrollPosition(id, position);
      }, 100),
      [setWorkspaceTabScrollPosition],
    );

    const onSelected = useCallback(
      (e) => {
        const id = e.currentTarget.id;
        setSelectedTab(id);
      },
      [setSelectedTab],
    );

    // Compute tab panels anytime the tabs change
    const tabPanels = useMemo(() => {
      return Object.keys(tabs).map((key) => {
        const tab = tabs[key];
        return html`<${TabPanel}
        id=${tab.id}
        title="${tab.label}"
        onSelected=${onSelected}
        selected=${selectedTab === tab.id}
        scrollable=${!!tab.scrollable}
        scrollPosition=${workspaceTabScrollPositionRef.current[tab.id]}
        setScrollPosition=${useCallback(
          (position) => {
            onScroll(tab.id, position);
          },
          [onScroll],
        )}
        >
          ${tab.content()}
        </${TabPanel}>`;
      });
    }, [tabs]);

    return html`
    
    
    <${Navbar}
      evalSpec=${evalSpec}
      evalPlan=${evalPlan}
      evalResults=${evalResults}
      evalStats=${evalStats}
      samples=${samples}
      status=${status}
      file=${logFileName}
      showToggle=${showToggle}
      
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
            ${tabPanels}
            </${TabSet}>
            </div>
          </div>`;
  }
};
