import { asyncJsonParse } from "../../../utils/json-worker";

type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface Request<T> {
  headers?: Record<string, string>;
  body?: string;
  parse?: (text: string) => Promise<T>;
  handleError?: (status: number) => T | undefined;
}

export type HeaderProvider = () => Promise<Record<string, string>>;

export interface ServerRequestApi {
  fetchString: (
    method: HttpMethod,
    path: string,
    headers?: Record<string, string>,
    body?: string,
  ) => Promise<{
    parsed: any;
    raw: string;
  }>;
  fetchBytes: (method: HttpMethod, path: string) => Promise<Uint8Array>;
  fetchType: <T>(
    method: HttpMethod,
    path: string,
    request: Request<T>,
  ) => Promise<{ raw: string; parsed: T }>;
}

export function serverRequestApi(
  baseUrl?: string,
  getHeaders?: HeaderProvider,
): ServerRequestApi {
  const apiUrl = baseUrl || "";

  function buildApiUrl(path: string): string {
    if (!apiUrl) {
      return path;
    }
    const base = apiUrl.endsWith("/") ? apiUrl.slice(0, -1) : apiUrl;
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    return base + cleanPath;
  }

  function isApiCrossOrigin(): boolean {
    try {
      return Boolean(
        apiUrl && new URL(apiUrl).origin !== window.location.origin,
      );
    } catch (error) {
      return false;
    }
  }

  const fetchType = async <T>(
    method: HttpMethod,
    path: string,
    request: Request<T>,
  ): Promise<{ raw: string; parsed: T }> => {
    const url = buildApiUrl(path);

    const responseHeaders: HeadersInit = {
      Accept: "application/json",
      Pragma: "no-cache",
      Expires: "0",
      "Cache-Control": "no-cache",
      ...request.headers,
    };

    if (getHeaders) {
      const globalHeaders = await getHeaders();
      Object.assign(responseHeaders, globalHeaders);
    }

    if (request.body) {
      responseHeaders["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers: responseHeaders,
      body: request.body,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });

    if (!response.ok) {
      const errorResponse = request.handleError?.(response.status);
      if (errorResponse) {
        return {
          raw: response.statusText,
          parsed: errorResponse,
        };
      }

      const message = (await response.text()) || response.statusText;
      throw new ApiError(
        response.status,
        `API Error ${response.status}: ${message}`,
      );
    }

    const text = await response.text();
    const parse = request.parse || asyncJsonParse;
    return {
      parsed: (await parse(text)) as T,
      raw: text,
    };
  };

  const fetchString = async (
    method: HttpMethod,
    path: string,
    headers?: Record<string, string>,
    body?: string,
  ): Promise<{ parsed: any; raw: string }> => {
    const url = buildApiUrl(path);

    const requestHeaders: HeadersInit = {
      Accept: "application/json",
      Pragma: "no-cache",
      Expires: "0",
      "Cache-Control": "no-cache",
      ...headers,
    };

    if (getHeaders) {
      const globalHeaders = await getHeaders();
      Object.assign(requestHeaders, globalHeaders);
    }

    if (body) {
      requestHeaders["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });

    if (response.ok) {
      const text = await response.text();
      return {
        parsed: await asyncJsonParse(text),
        raw: text,
      };
    }

    const message = (await response.text()) || response.statusText;
    throw new ApiError(response.status, `HTTP ${response.status}: ${message}`);
  };

  const fetchBytes = async (
    method: HttpMethod,
    path: string,
  ): Promise<Uint8Array> => {
    const url = buildApiUrl(path);

    const headers: HeadersInit = {
      Accept: "application/octet-stream",
      Pragma: "no-cache",
      Expires: "0",
      "Cache-Control": "no-cache",
    };

    if (getHeaders) {
      const globalHeaders = await getHeaders();
      Object.assign(headers, globalHeaders);
    }

    const response = await fetch(url, {
      method,
      headers,
      credentials: isApiCrossOrigin() ? "include" : "same-origin",
    });

    if (!response.ok) {
      const message = (await response.text()) || response.statusText;
      throw new ApiError(
        response.status,
        `HTTP ${response.status}: ${message}`,
      );
    }

    const buffer = await response.arrayBuffer();
    return new Uint8Array(buffer);
  };

  return {
    fetchString,
    fetchBytes,
    fetchType,
  };
}
