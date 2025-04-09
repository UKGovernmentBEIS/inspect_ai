import * as vscode from "vscode";

export function disposeAll(disposables: vscode.Disposable[]) {
  while (disposables.length) {
    const item = disposables.pop();
    item?.dispose();
  }
}

export abstract class Disposable {
  private _isDisposed = false;

  protected _disposables: vscode.Disposable[] = [];

  public dispose(): unknown {
    if (this._isDisposed) {
      return;
    }
    this._isDisposed = true;
    disposeAll(this._disposables);
  }

  protected _register<T extends vscode.Disposable>(value: T): T {
    if (this._isDisposed) {
      value.dispose();
    } else {
      this._disposables.push(value);
    }
    return value;
  }

  protected get isDisposed() {
    return this._isDisposed;
  }
}
