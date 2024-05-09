import { existsSync, readFileSync, writeFileSync } from "fs";
import { lines } from "./text";
import { Uri } from "vscode";

export const readEnv = (file: Uri): Record<string, string> => {
  // There is no env file, no env settings
  if (!existsSync(file.fsPath)) {
    return {};
  }

  // Read the env file
  const envLines = readEnvLines(file);

  // Read the env file
  return envLines
    .map((line) => {
      return readLine(line);
    })
    .reduce((prev, current) => {
      if (current) {
        prev[current.key] = current?.value;
      }
      return prev;
    }, {} as Record<string, string>);
};

export const writeEnv = (key: string, value: string, file: Uri) => {
  // Read the env file
  const envLines = existsSync(file.fsPath) ? readEnvLines(file) : [];
  const outLines = [];

  let valueWritten = false;
  for (const line of envLines) {
    const parsed = readLine(line);
    if (parsed?.key === key) {
      outLines.push(toLine(key, value));
      valueWritten = true;
    } else {
      outLines.push(line);
    }
  }
  if (!valueWritten) {
    outLines.push(toLine(key, value));
  }

  writeFileSync(file.fsPath, outLines.join("\n"), { encoding: "utf-8" });
};

export const clearEnv = (key: string, file: Uri) => {
  // Read the env file
  const envLines = existsSync(file.fsPath) ? readEnvLines(file) : [];
  const outLines = [];

  for (const line of envLines) {
    const parsed = readLine(line);
    if (parsed?.key !== key) {
      outLines.push(line);
    }
  }
  writeFileSync(file.fsPath, outLines.join("\n"), { encoding: "utf-8" });
};

function readLine(line: string) {
  const trimmed = line.trim();

  // Comment
  if (trimmed.startsWith("#")) {
    return undefined;
  }

  const eqIdx = trimmed.indexOf("=");
  if (eqIdx < 0) {
    return undefined;
  }

  const key = trimmed.substring(0, eqIdx).trim();
  let value = trimmed.substring(eqIdx + 1).trim();

  ["'", '"'].forEach((quote) => {
    if (value.startsWith(quote) && value.endsWith(quote)) {
      value = value.substring(quote.length, value.length - quote.length);
    }
  });

  return { key, value };
}

function readEnvLines(file: Uri) {
  const envRaw = readFileSync(file.fsPath, { encoding: "utf-8" });
  return lines(envRaw);
}

function toLine(key: string, value: string) {
  const needsQuote = [" ", "'", '"'].some((char) => {
    return value.indexOf(char) > -1;
  });

  const quoteChar = !needsQuote ? "" : value.indexOf('"') > -1 ? "'" : '"';
  return `${key}=${quoteChar}${value}${quoteChar}`;
}
