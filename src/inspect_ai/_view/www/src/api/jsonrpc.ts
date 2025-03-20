// Type definitions
interface JsonRpcMessage {
  jsonrpc: string;
  id: number;
}

interface JsonRpcRequest extends JsonRpcMessage {
  method: string;
  params?: any;
}

interface JsonRpcResponse extends JsonRpcMessage {
  result?: any;
  error?: JsonRpcError;
}

interface JsonRpcError {
  code: number;
  message: string;
  data?: {
    description?: string;
    [key: string]: any;
  };
}

interface RequestHandlers {
  resolve: (value: any) => void;
  reject: (error: JsonRpcError) => void;
}

interface PostMessageTarget {
  postMessage: (data: any) => void;
  onMessage: (handler: (data: any) => void) => () => void;
}

// Constants
export const kMethodEvalLogs = "eval_logs";
export const kMethodEvalLog = "eval_log";
export const kMethodEvalLogSize = "eval_log_size";
export const kMethodEvalLogBytes = "eval_log_bytes";
export const kMethodEvalLogHeaders = "eval_log_headers";
export const kMethodPendingSamples = "eval_log_pending_samples";
export const kMethodSampleData = "eval_log_sample_data";

export const kJsonRpcParseError = -32700;
export const kJsonRpcInvalidRequest = -32600;
export const kJsonRpcMethodNotFound = -32601;
export const kJsonRpcInvalidParams = -32602;
export const kJsonRpcInternalError = -32603;
export const kJsonRpcVersion = "2.0";

export function webViewJsonRpcClient(
  vscode: any,
): (method: string, params?: any) => Promise<any> {
  const target: PostMessageTarget = {
    postMessage: (data: any) => {
      vscode.postMessage(data);
    },
    onMessage: (handler: (data: any) => void) => {
      const onMessage = (ev: MessageEvent) => {
        handler(ev.data);
      };
      window.addEventListener("message", onMessage);
      return () => {
        window.removeEventListener("message", onMessage);
      };
    },
  };
  return jsonRpcPostMessageRequestTransport(target).request;
}

export function jsonRpcError(
  message: string,
  data?: any,
  code?: number,
): JsonRpcError {
  if (typeof data === "string") {
    data = {
      description: data,
    };
  }
  return {
    code: code || -3200,
    message,
    data,
  };
}

export function asJsonRpcError(error: unknown): JsonRpcError {
  if (typeof error === "object" && error !== null) {
    const err = error as { message?: string; data?: any; code?: number };
    if (typeof err.message === "string") {
      return jsonRpcError(err.message, err.data, err.code);
    }
  }
  return jsonRpcError(String(error));
}

export function jsonRpcPostMessageRequestTransport(target: PostMessageTarget) {
  const requests = new Map<number, RequestHandlers>();
  const disconnect = target.onMessage((ev: any) => {
    const response = asJsonRpcResponse(ev);
    if (response) {
      const request = requests.get(response.id);
      if (request) {
        requests.delete(response.id);
        if (response.error) {
          request.reject(response.error);
        } else {
          request.resolve(response.result);
        }
      }
    }
  });

  return {
    request: (method: string, params?: any): Promise<any> => {
      return new Promise((resolve, reject) => {
        const requestId = Math.floor(Math.random() * 1e6);
        requests.set(requestId, { resolve, reject });
        const request: JsonRpcRequest = {
          jsonrpc: kJsonRpcVersion,
          id: requestId,
          method,
          params,
        };
        target.postMessage(request);
      });
    },
    disconnect,
  };
}

export function jsonRpcPostMessageServer(
  target: PostMessageTarget,
  methods:
    | { [key: string]: (params: any) => Promise<any> }
    | ((name: string) => ((params: any) => Promise<any>) | undefined),
): () => void {
  const lookupMethod =
    typeof methods === "function" ? methods : (name: string) => methods[name];

  return target.onMessage((data: any) => {
    const request = asJsonRpcRequest(data);
    if (request) {
      const method = lookupMethod(request.method);
      if (!method) {
        target.postMessage(methodNotFoundResponse(request));
        return;
      }

      method(request.params || [])
        .then((value) => {
          target.postMessage(jsonRpcResponse(request, value));
        })
        .catch((error) => {
          target.postMessage({
            jsonrpc: request.jsonrpc,
            id: request.id,
            error: asJsonRpcError(error),
          });
        });
    }
  });
}

function isJsonRpcMessage(message: any): message is JsonRpcMessage {
  return message.jsonrpc !== undefined && message.id !== undefined;
}

function isJsonRpcRequest(message: JsonRpcMessage): message is JsonRpcRequest {
  return (message as JsonRpcRequest).method !== undefined;
}

function asJsonRpcMessage(data: any): JsonRpcMessage | null {
  if (isJsonRpcMessage(data) && data.jsonrpc === kJsonRpcVersion) {
    return data;
  }
  return null;
}

function asJsonRpcRequest(data: any): JsonRpcRequest | null {
  const message = asJsonRpcMessage(data);
  if (message && isJsonRpcRequest(message)) {
    return message;
  }
  return null;
}

function asJsonRpcResponse(data: any): JsonRpcResponse | null {
  const message = asJsonRpcMessage(data);
  if (message) {
    return message as JsonRpcResponse;
  }
  return null;
}

function jsonRpcResponse(
  request: JsonRpcRequest,
  result: any,
): JsonRpcResponse {
  return {
    jsonrpc: request.jsonrpc,
    id: request.id,
    result,
  };
}

function jsonRpcErrorResponse(
  request: JsonRpcRequest,
  code: number,
  message: string,
): JsonRpcResponse {
  return {
    jsonrpc: request.jsonrpc,
    id: request.id,
    error: jsonRpcError(message, undefined, code),
  };
}

function methodNotFoundResponse(request: JsonRpcRequest): JsonRpcResponse {
  return jsonRpcErrorResponse(
    request,
    kJsonRpcMethodNotFound,
    `Method '${request.method}' not found.`,
  );
}
