import { Disposable, commands } from "vscode";

export interface Command {
  readonly id: string;

  execute(...args: unknown[]): void;
}

export class CommandManager {
  private readonly commands = new Map<string, Disposable>();

  public dispose() {
    for (const registration of this.commands.values()) {
      registration.dispose();
    }
    this.commands.clear();
  }

  public register<T extends Command>(command: T): T {
    // eslint-disable-next-line @typescript-eslint/unbound-method
    this.registerCommand(command.id, command.execute, command);
    return command;
  }

  private registerCommand(
    id: string,
    impl: (...args: unknown[]) => void,
    thisArg?: unknown
  ) {
    if (this.commands.has(id)) {
      return;
    }

    this.commands.set(id, commands.registerCommand(id, impl, thisArg));
  }
}