import { ExtensionContext, Uri } from "vscode";

const kMruListSize = 10;
const kMruKey = 'inspect_ai.log-listing-mru';


export class LogListingMRU {
  constructor(private readonly context_: ExtensionContext) { }

  public get(): Uri[] {
    return this.getStoredMRU().map((uri) => Uri.parse(uri));
  }

  public async add(logLocation: Uri): Promise<void> {
    // start with current mru
    const currentMru = this.getStoredMRU();

    // remove then add so its at the front
    const filteredMru = currentMru.filter(str => str !== logLocation.toString());
    filteredMru.unshift(logLocation.toString());

    // trim to max size
    const newMru = filteredMru.slice(0, kMruListSize);

    // save back to workspace state
    await this.context_.workspaceState.update(kMruKey, newMru);
  }


  public async remove(logLocation: Uri): Promise<void> {
    // remove the uri
    const currentMru = this.getStoredMRU();
    const newMru = currentMru.filter(str => str !== logLocation.toString());

    // save back to workspace state
    await this.context_.workspaceState.update(kMruKey, newMru);
  }

  public async clear(): Promise<void> {
    await this.context_.workspaceState.update(kMruKey, []);
  }

  private getStoredMRU(): string[] {
    return this.context_.workspaceState.get<string[]>(kMruKey) || [];
  }
}


