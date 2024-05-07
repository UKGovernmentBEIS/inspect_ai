import {
    window,
  } from "vscode";

  

export async function showError(msg: string, error?: Error) {
    const message = [msg];
    if (error) {
        message.push(error.message);
    }
    await window.showErrorMessage(message.join("\n"), "Ok");
}