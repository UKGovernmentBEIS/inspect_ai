var kMethodEvalLogs = "eval_logs";

var kMethodEvalLog = "eval_log";

var kMethodEvalLogSize = "eval_log_size";
var kMethodEvalLogBytes = "eval_log_bytes";

var kMethodEvalLogHeaders = "eval_log_headers";

function webViewJsonRpcClient(vscode) {
  var target = {
    postMessage: function (data) {
      vscode.postMessage(data);
    },
    onMessage: function (handler) {
      var onMessage = function (ev) {
        handler(ev.data);
      };
      window.addEventListener("message", onMessage);
      return function () {
        window.removeEventListener("message", onMessage);
      };
    },
  };
  var request = jsonRpcPostMessageRequestTransport(target).request;
  return request;
}

var kJsonRpcParseError = -32700;

var kJsonRpcInvalidRequest = -32600;

var kJsonRpcMethodNotFound = -32601;

var kJsonRpcInvalidParams = -32602;

var kJsonRpcInternalError = -32603;

function jsonRpcError(message, data, code) {
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

function asJsonRpcError(error) {
  if (typeof error === "object") {
    var err = error;
    if (typeof err.message === "string") {
      return jsonRpcError(err.message, err.data, err.code);
    }
  }
  return jsonRpcError(String(error));
}

function jsonRpcPostMessageRequestTransport(target) {
  var requests = new Map();
  var disconnect = target.onMessage(function (ev) {
    var response = asJsonRpcResponse(ev);
    if (response) {
      var request = requests.get(response.id);
      if (request) {
        requests["delete"](response.id);
        if (response.error) {
          request.reject(response.error);
        } else {
          request.resolve(response.result);
        }
      }
    }
  });
  return {
    request: function (method, params) {
      return new Promise(function (resolve, reject) {
        var requestId = Math.floor(Math.random() * 1e6);
        requests.set(requestId, {
          resolve,
          reject,
        });
        var request = {
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

function jsonRpcPostMessageServer(target, methods) {
  var lookupMethod =
    typeof methods === "function"
      ? methods
      : function (name) {
          return methods[name];
        };
  return target.onMessage(function (data) {
    var request = asJsonRpcRequest(data);
    if (request) {
      var method = lookupMethod(request.method);
      if (!method) {
        target.postMessage(methodNotFoundResponse(request));
        return;
      }
      /* eslint-disable no-unexpected-multiline */
      method(request.params || [])
        .then(function (value) {
          target.postMessage(jsonRpcResponse(request, value));
        })
        ["catch"](function (error) {
          target.postMessage({
            jsonrpc: request.jsonrpc,
            id: request.id,
            error: asJsonRpcError(error),
          });
        });
      /* eslint-enable no-unexpected-multiline */
    }
  });
}

var kJsonRpcVersion = "2.0";

function isJsonRpcMessage(message) {
  var jsMessage = message;
  return jsMessage.jsonrpc !== undefined && jsMessage.id !== undefined;
}

function isJsonRpcRequest(message) {
  return message.method !== undefined;
}

function asJsonRpcMessage(data) {
  if (isJsonRpcMessage(data) && data.jsonrpc === kJsonRpcVersion) {
    return data;
  } else {
    return null;
  }
}

function asJsonRpcRequest(data) {
  var message = asJsonRpcMessage(data);
  if (message && isJsonRpcRequest(message)) {
    return message;
  } else {
    return null;
  }
}

function asJsonRpcResponse(data) {
  var message = asJsonRpcMessage(data);
  if (message) {
    return message;
  } else {
    return null;
  }
}

function jsonRpcResponse(request, result) {
  return {
    jsonrpc: request.jsonrpc,
    id: request.id,
    result,
  };
}

function jsonRpcErrorResponse(request, code, message) {
  return {
    jsonrpc: request.jsonrpc,
    id: request.id,
    error: jsonRpcError(message, undefined, code),
  };
}

function methodNotFoundResponse(request) {
  return jsonRpcErrorResponse(
    request,
    kJsonRpcMethodNotFound,
    "Method '".concat(request.method, "' not found."),
  );
}

export {
  asJsonRpcError,
  jsonRpcError,
  jsonRpcPostMessageRequestTransport,
  jsonRpcPostMessageServer,
  kJsonRpcInternalError,
  kJsonRpcInvalidParams,
  kJsonRpcInvalidRequest,
  kJsonRpcMethodNotFound,
  kJsonRpcParseError,
  webViewJsonRpcClient,
  kMethodEvalLog,
  kMethodEvalLogSize,
  kMethodEvalLogBytes,
  kMethodEvalLogs,
  kMethodEvalLogHeaders,
};
