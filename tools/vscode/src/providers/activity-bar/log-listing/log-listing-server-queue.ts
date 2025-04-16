import * as vscode from "vscode";
import { LogListing, LogNode } from "./log-listing";
import { EvalLog, EvalResults } from "../../../@types/log";
import path from "path";
import { MarkdownString } from "vscode";
import { stringify } from "yaml";
import { sleep } from "../../../core/wait";

export const kLogListCacheName = "logListingCache";

export class LogElementQueueProcessor {
  private queue: LogNode[] = [];
  private isProcessing = false;
  private elementCache = new Map<
    string,
    {
      iconPath?: string | vscode.ThemeIcon;
      tooltip?: vscode.MarkdownString;
    }
  >();
  private processingTimeout: NodeJS.Timeout | null = null;

  constructor(
    private readonly viewServer: {
      evalLogHeaders: (uris: string[]) => Promise<string | undefined>;
    },
    private readonly logListing: () => LogListing | undefined,
    private readonly context: vscode.ExtensionContext,
    private readonly onElementUpdated: (element: LogNode) => void,
    private readonly batchSize: number = 10,
  ) {
    // Load cache from workspace storage
    const savedCache =
      this.context.workspaceState.get<
        Map<string, { iconPath?: string; tooltip?: vscode.MarkdownString }>
      >(kLogListCacheName);
    if (savedCache) {
      this.elementCache = new Map(savedCache);
    } else {
      this.elementCache = new Map();
    }
  }

  enqueueElement(element: LogNode): void {
    this.queue.push(element);

    // Only start a new timeout if one isn't already running
    if (!this.processingTimeout) {
      this.processingTimeout = setTimeout(() => {
        void this.processQueue();
      }, 50);
    }
  }

  private async processQueue(): Promise<void> {
    // Clear the timeout reference since we're starting processing
    this.processingTimeout = null;

    // Don't start processing if already running or queue is empty
    if (this.isProcessing || this.queue.length === 0) {
      return;
    }
    this.isProcessing = true;

    // Process elements in batches
    const elements = this.queue.slice(0, this.batchSize);

    try {
      // Collect all URIs
      const elementUris = new Map<string, LogNode>();
      elements.forEach((element) => {
        const listing = this.logListing();
        const uri = listing?.uriForNode(element);
        if (uri) {
          elementUris.set(uri.toString(), element);
        }
      });
      const allUris = Array.from(elementUris.keys());

      // Handle cached elements (if they're in the cache,
      // screen them out after populating them from cache)
      const uris = allUris.filter((uri) => {
        const cached = this.elementCache.get(uri);
        if (cached) {
          const el = elementUris.get(uri);
          if (el) {
            el.iconPath = cached.iconPath;
            el.tooltip = cached.tooltip;
            this.onElementUpdated(el);
            return false;
          }
        }
        return true;
      });

      if (uris.length > 0) {
        // Fetch headers
        const headers = await this.viewServer.evalLogHeaders(uris);

        if (headers !== undefined) {
          const evalLogs = JSON.parse(headers) as EvalLog[];

          // Update elements with their corresponding evalLog
          for (let i = 0; i < evalLogs.length; i++) {
            const evalLog = evalLogs[i];
            const uri = uris[i];
            const element = elementUris.get(uri);
            if (element && evalLog?.version === 2) {
              // Populate the server provided props
              element.iconPath = iconForStatus(
                this.context,
                element,
                evalLog.status,
              );
              element.tooltip = evalSummary(element, evalLog);

              // Cache completed elements
              const listing = this.logListing();
              const nodeUri = listing?.uriForNode(element);
              if (nodeUri && evalLog.status !== "started") {
                this.elementCache.set(nodeUri.toString(), {
                  iconPath: element.iconPath,
                  tooltip: element.tooltip,
                });

                // Persist the cache
                await this.context.workspaceState.update(
                  kLogListCacheName,
                  Array.from(this.elementCache.entries()),
                );
                this.enforceCacheLimit();
              }

              // Notify that the element was updated
              this.onElementUpdated(element);
            }
          }
        }
      }
    } catch (error) {
      console.error("Error processing icon refresh queue:", error);
      this.queue = [];
    } finally {
      // Remove processed elements
      this.queue = this.queue.filter((item) => !elements.includes(item));
      this.isProcessing = false;

      // Process remaining items if any
      if (this.queue.length > 0) {
        await sleep(5000);
        await this.processQueue();
      }
    }
  }

  clearCache(): void {
    this.elementCache.clear();
  }

  enforceCacheLimit(): void {
    // Evict the least recently used item if this exceeds
    // the max size
    if (this.elementCache.size > 500) {
      const keys = Array.from(this.elementCache.keys());
      this.elementCache.delete(keys[0]);
    }
  }

  public cachedValue(uri: string):
    | {
        iconPath?: string | vscode.ThemeIcon;
        tooltip?: vscode.MarkdownString;
      }
    | undefined {
    return this.elementCache.get(uri);
  }
}

function iconForStatus(
  context: vscode.ExtensionContext,
  element: LogNode,
  status?: string,
) {
  if (element.name.endsWith(".eval")) {
    let modifier = undefined;
    switch (status) {
      case "started":
        modifier = "started";
        break;
      case "cancelled":
        modifier = "cancelled";
        break;
      case "error":
        modifier = "error";
        break;
    }

    if (modifier) {
      return context.asAbsolutePath(
        path.join("assets", "icon", `eval-treeview-${modifier}.svg`),
      );
    } else {
      return context.asAbsolutePath(
        path.join("assets", "icon", "eval-treeview.svg"),
      );
    }
  } else {
    return new vscode.ThemeIcon(
      "bracket",
      new vscode.ThemeColor("symbolIcon.classForeground"),
    );
  }
}

export function evalSummary(
  node: LogNode,
  log: EvalLog,
): MarkdownString | undefined {
  // build summary
  const summary = evalHeader(log);

  // results
  if (log.results) {
    summary.push("  ");
    summary.push(...evalResults(log.results));
  }

  // params / config
  const config = evalConfig(log);
  if (config) {
    summary.push(...config);
  }

  if (summary.length > 0) {
    return new MarkdownString(summary.join("\n  "), true);
  } else {
    return undefined;
  }
}

function evalHeader(log: EvalLog): string[] {
  const kMinWidth = 60;
  const title = `### ${log.eval.task} - ${log.eval.model}`;
  const padding = "&nbsp;".repeat(Math.max(kMinWidth - title.length, 0));
  return [`${title}${padding}`, evalTarget(log)];
}

function evalTarget(log: EvalLog): string {
  // setup target
  const target: string[] = [];
  if (log.status !== "success") {
    target.push(`status:&nbsp;${log.status}`);
  }

  // dataset
  const dataset: string[] = ["dataset:"];
  if (log.eval.dataset.name) {
    dataset.push(log.eval.dataset.name);
  }
  if (log.eval.dataset.samples) {
    const eval_epochs = log.eval.config.epochs || 1;
    const epochs = eval_epochs > 1 ? ` x ${eval_epochs}` : "";
    dataset.push(
      `(${log.eval.dataset.samples}${epochs} sample` +
        (log.eval.dataset.samples > 1 ? "s" : "") +
        ")",
    );
  }
  if (dataset.length === 1) {
    dataset.push("(samples)");
  }
  target.push(dataset.join(" "));

  // scorers
  if (log.results) {
    const scorer_names = new Set<string>(
      log.results.scores.map((score) => score.scorer),
    );
    target.push("scorers: " + Array.from(scorer_names).join(", "));
  }

  return target.join("  \n");
}

function evalConfig(log: EvalLog): string[] | undefined {
  let config: Record<string, unknown> = {};

  // task args
  const taskArgs = log.eval.task_args as Record<string, unknown>;
  for (const arg of Object.keys(taskArgs)) {
    let value = taskArgs[arg];
    if (isObject(value) && Object.keys(value).includes("name")) {
      value = value["name"];
    }
    config[arg] = value;
  }

  // eval config and generate config
  config = { ...config, ...log.eval.config, ...log.plan?.config };

  // remove some params
  delete config["model"];
  delete config["log_images"];

  if (Object.keys(config).length > 0) {
    return ["```", `${stringify(config)}`, "```"];
  } else {
    return undefined;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function evalResults(results: EvalResults): string[] {
  const scorer_names = new Set<string>(
    results.scores.map((score) => score.name),
  );
  const reducer_names = new Set<string>(
    results.scores
      .filter((score) => score.reducer !== null)
      .map((score) => score.reducer || ""),
  );
  const show_reducer = reducer_names.size > 1 || !reducer_names.has("avg");
  const output: Record<string, string> = {};
  for (const score of results.scores) {
    for (const metricName of Object.keys(score.metrics)) {
      const metricValue = score.metrics[metricName];
      const value =
        metricValue.value === 1 ? "1.0" : formatNumber(metricValue.value);
      const name =
        show_reducer && score.reducer
          ? `${metricName}[${score.reducer}]`
          : metricName;
      const key = scorer_names.size > 1 ? `${score.name}/${name}` : name;
      output[key] = value;
    }
  }

  const markdown: string[] = [];
  for (const key of Object.keys(output)) {
    const value = output[key];
    markdown.push(`${key}: ${value}`);
  }
  return [`**${markdown.join(", ")}**`];
}

function formatNumber(num: number) {
  return Number(num) === Math.floor(num)
    ? num.toString()
    : num.toFixed(3).replace(/\.?0+$/, "");
}
