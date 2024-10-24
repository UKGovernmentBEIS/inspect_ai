

import * as path from 'path';

import { format, isToday, isThisYear } from 'date-fns';


import { Event, EventEmitter, TreeDataProvider, TreeItem, TreeItemCollapsibleState } from 'vscode';

import * as vscode from 'vscode';
import { LogNode, LogListing } from './log-listing';
import { prettyUriPath } from '../../../core/uri';
import { throttle } from 'lodash';


export class LogTreeDataProvider implements TreeDataProvider<LogNode>, vscode.Disposable {

  public static readonly viewType = "inspect_ai.logs-view";

  private readonly throttledRefresh_: () => void;

  constructor(private context_: vscode.ExtensionContext) {
    this.throttledRefresh_ = throttle(() => {
      this.logListing_?.invalidate();
      this._onDidChangeTreeData.fire();
    }, 1000);
  }

  dispose() {

  }

  public setLogListing(logListing: LogListing) {
    this.logListing_ = logListing;
    this.refresh();
  }

  public getLogListing(): LogListing | undefined {
    return this.logListing_;
  }


  public refresh(): void {
    this.throttledRefresh_();
  }

  getTreeItem(element: LogNode): TreeItem {

    // base tree item
    const treeItem: TreeItem = {
      id: element.name,
      iconPath: element.type === "file"
        ? element.name.endsWith(".eval")
          ? this.context_.asAbsolutePath(path.join("assets", "icon", "eval.svg"))
          : new vscode.ThemeIcon("bracket", new vscode.ThemeColor("symbolIcon.classForeground"))
        : undefined,
      label: element.name.split("/").pop(),
      collapsibleState: element.type === "dir"
        ? TreeItemCollapsibleState.Collapsed
        : TreeItemCollapsibleState.None,
    };

    // make file display nicer
    if (element.type === "file") {
      treeItem.label = element.task || "task";
      const date = parseLogDate(element.name.split("/").pop()!);
      treeItem.description = `${formatPrettyDateTime(date)}`;

    }

    // open files in the editor
    if (element.type === "file") {
      treeItem.command = {
        command: 'vscode.open',
        title: 'View Inspect Log',
        arguments: [this.logListing_?.uriForNode(element), <vscode.TextDocumentShowOptions>{ preview: true }]
      };
    }

    return treeItem;
  }

  async getChildren(element?: LogNode): Promise<LogNode[]> {
    if (!element || element.type === "dir") {
      return await this.logListing_?.ls(element) || [];
    } else {
      return [];
    }
  }

  async resolveTreeItem?(
    item: TreeItem,
    element: LogNode
  ): Promise<TreeItem> {
    const nodeUri = this.logListing_?.uriForNode(element);
    if (nodeUri) {
      item.tooltip = prettyUriPath(nodeUri);
    }
    return Promise.resolve(item);
  }


  private _onDidChangeTreeData: EventEmitter<LogNode | undefined | null | void> = new vscode.EventEmitter<LogNode | undefined | null | void>();
  readonly onDidChangeTreeData: Event<LogNode | undefined | null | void> = this._onDidChangeTreeData.event;


  private logListing_?: LogListing;
}


function parseLogDate(logName: string) {

  // Take only first bit
  const logDate = logName.split("_")[0];

  // Input validation
  if (!logDate.match(/^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}[+-]\d{2}-\d{2}$/)) {
    throw new Error(`Unexpcted date format. Expected format: YYYY-MM-DDThh-mm-ss+hh-mm or YYYY-MM-DDThh-mm-ss-hh-mm, got ${logDate}`);
  }

  // Convert hyphens to colons only in the time portion (after T) and timezone
  // Leave the date portion (before T) unchanged
  const normalized = logDate.replace(/T(\d{2})-(\d{2})-(\d{2})([+-])(\d{2})-(\d{2})/, 'T$1:$2:$3$4$5:$6');
  const result = new Date(normalized);
  if (isNaN(result.getTime())) {
    throw new Error(`Failed to parse date string: ${normalized}`);
  }

  return result;
}


function formatPrettyDateTime(date: Date) {

  // For today, just show time
  if (isToday(date)) {
    return `Today, ${format(date, 'h:mmaaa')}`;
  }

  // For this year, show month and day
  if (isThisYear(date)) {
    return format(date, 'MMM d, h:mmaaa');
  }

  // For other years, include the year
  return format(date, 'MMM d yyyy, h:mmaaa');
}