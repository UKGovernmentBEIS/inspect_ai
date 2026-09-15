# Viewer scoped authorization (inspect_ai)

Server-enforced scoping for the Inspect view server. A client that holds a credential the server can verify declares the scope of each request in a standard bearer JWT; the VS Code extension is the first such client and attaches a per-panel JWT to every Inspect log-panel request.

Revision 7, final (2026-09-14; revisions 6 and 7 by CASE from Charles's decisions in `decisions.md`; revision 7 after reading METR/hawk `main` 1b73989). Written against inspect_ai `main` 18b1348be (release 0.3.263), inspect_vscode `origin/main` 118a8083 (release 0.9.19), ts-mono 02f2c5ad as pinned by inspect_ai, and METR/hawk `main` as read on GitHub today. Facts not established from those sources are marked as assumptions.

## Summary

In token mode the Inspect view server installs no access policy (`standalone_view_app` in `src/inspect_ai/_view/fastapi_server.py`), because one shared server serves many panels with different scopes. The extension confines webview requests from outside, in `src/core/package/proxy-scope.ts`, by re-parsing every server route; the open findings are the residue of the host's model of the server drifting from the server.

This design moves the decision into the server and states it as a general security model rather than a contract with one client. The server always has a scope. Without a credential it is the startup scope (`log_dir`), as the browser path works today. A request carrying a bearer JWT the server can verify takes the scope declared in the token's claims. Deployments with their own identity provider do not use inspect_ai's authentication at all: they embed `view_server_app` behind their own middleware and policies, which is what METR's Hawk does today and what this design keeps as the general path. The raw opaque master token remains accepted as a legacy credential meaning today's unscoped behaviour, so that existing clients keep working, and a server option turns it off. The extension mints one JWT per Inspect log panel at creation with a standard library and attaches it to every request; any client that holds the shared secret can do the same with stock JWT tooling and the documented claim schema. The server verifies the token in middleware with a library, algorithm list pinned, and routes every location through one resolution layer that returns the canonical location used for I/O or raises 403. The extension's Inspect route table stops being the primary control and becomes the compatibility path, kept for good, for servers that do not enforce scope: a new extension must always work against an older installed inspect_ai. The standalone browser server keeps its token-less `log_dir` confinement, reimplemented on the same canonicalizer.

The public `AccessPolicy` and `FileMappingPolicy` protocols are unchanged. METR's Hawk implements both (`hawk/hawk/api/server_policies.py`) against `view_server_app`, and this design keeps such implementations working without edits. The canonical-location property comes from a resolver layer that wraps a plain policy (section 3).

Scout, both server and extension half, is out of scope. The wire contract is defined so Scout can adopt it later without a version bump; the constraints and the Scout-side findings left open are collected in the appendix.

## 1. Credential: a standard bearer JWT

**Why a standard.** The first version of this design carried the scope in a purpose-built signed token, chosen to minimize code between two parties Meridian controls. Charles's decision (2026-09-14) reframed the requirement: the server should have a security model any client can adopt with stock tooling, not one bent to the VS Code extension. A bearer JWT is that model. Scope is a claim, keys are standard, verification is a library call, and a third party integrating a viewer, a gateway or a notebook needs nothing Inspect-specific beyond the claim schema in section 2.

**Wire form.** `Authorization: Bearer <jwt>`. The server verifies with PyJWT (`jwt.decode(token, key, algorithms=[...], audience=...)`), algorithms pinned to the configured list, and reads the scope from the `inspect_view_scope` claim. Standard claims do the jobs a bespoke format would have hand-rolled:

| Claim | Use |
|---|---|
| `inspect_view_scope` | the scope (section 2) |
| `aud` | the server's audience string, so a token minted for one deployment is refused by another |
| `exp` | token lifetime; the extension re-mints before expiry |
| `iat`, `sub`, `jti` | optional; `sub` is the panel or user identifier for diagnostics only, no authority |

**Keys.** One configuration: HS256 with a shared secret, the value already passed in `INSPECT_VIEW_AUTHORIZATION_TOKEN`. The extension generates it per server process (`randomUUID()` per `ServerInstance` in `view-server.ts`) and passes it in the environment, so it can mint tokens and the server can verify them with no new plumbing. Because the secret is per process, a token is bound to one server instance. No asymmetric keys, no JWKS URL, no audience option: `aud` is the fixed string `inspect-view` and `exp` is required. The algorithm list passed to the library is `["HS256"]` and nothing else; the token's `alg` header is never trusted to choose, and `none` is never accepted. Verification failures of any kind are 401; a verified token whose `inspect_view_scope` claim fails schema validation is also 401, so a malformed scope never reaches a route.

**Why not public keys here.** An identity-provider deployment does not need inspect_ai to verify its tokens, because the embedding contract already lets it do that itself. METR's Hawk (`hawk/api/eval_log_server.py`, read at `main` 1b73989) embeds the bare `view_server_app`, not `standalone_view_app`, and wraps it in its own middleware: an access-token middleware validating Cognito OIDC JWTs against the provider's JWKS with `joserfc`, taking the token from `Authorization: Bearer` for the CLI or the `inspect_ai_access_token` cookie for the viewer; read-only enforcement; CORS. Authentication leaves an auth context on `request.state`; authorization is Hawk's `AccessPolicy` subclass, which keys `can_read` on the eval-set folder the path belongs to and the caller's permissions; its `FileMappingPolicy` maps bucket-relative paths to S3. Hawk does the same for Scout by wrapping Scout's v2 API app. That is the general model, it exists, and it is in production. This design leaves it exactly as it is and documents it as the supported path (section 3, "Embedding contract"). inspect_ai's own `standalone_view_app` therefore needs only the one JWT case that its only authenticated client, the extension, uses.

**Legacy credential.** `Authorization: <master token>` (the raw shared secret, compared with `secrets.compare_digest`) remains accepted and means today's unscoped behaviour (`UnscopedResolvingPolicy`, section 3). This is what every existing client sends, including every released extension. The server option `--require-scoped-authorization` / `INSPECT_VIEW_REQUIRE_SCOPED_AUTHORIZATION=1` refuses it on every route except `/api/app-config`; it is off by default in release A and its default may flip in a later release once clients have migrated (section 5). The server tells the two apart by shape: a JWT has three base64url segments separated by dots and a `Bearer ` prefix; the master token is an opaque UUID.

**Libraries.** inspect_ai adds one JWT library for HS256 only. Hawk already depends on both `pyjwt` and `joserfc`, so either is compatible with the largest embedder; `pyjwt` is the smaller dependency and needs no `cryptography` extra for HS256. The extension adds `jose` (`SignJWT` with HS256). Neither repository writes signing or verification code.

**Other clients.** A script or notebook that starts `inspect view` with a secret mints an HS256 token with that secret for the directory it wants to show. A team viewer behind an identity provider follows the Hawk pattern and never involves inspect_ai's authentication. The extension is the only client of `standalone_view_app`'s JWT path today.

## 2. Capability model

A scope is a set of roots with per-root permissions, carried as the `inspect_view_scope` claim of the JWT.

```json
{
  "aud": "inspect-view",
  "exp": 1789420000,
  "sub": "logview:3f9c1b",
  "inspect_view_scope": {
    "v": 1,
    "roots": [
      {"uri": "file:///w/logs", "kind": "dir", "permissions": ["read", "list", "write"]}
    ]
  }
}
```

- `sub`: panel or user identifier for diagnostics only; no authority.
- `roots[].uri`: absolute `file://`, `s3://`, `gs://`, `az://` or `http(s)://` URI. `kind` is `dir` or `file`; `http(s)` roots must be `file` and are held as opaque exact URLs. `permissions` is a subset of `read`, `list`, `write`, `delete`.

**Validation rules** (applied to the claim after the JWT itself has verified). Empty `roots` is 401 unless a reserved grant field is present (appendix). Unknown fields inside the claim are ignored, not rejected, so fields can be added later without a version bump. Unknown permission strings are ignored and never grant anything. `kind` outside `dir` / `file` is 401. `v` other than 1 is 401; the version is bumped only if the meaning of an existing field changes. Other JWT claims are handled by the library and by the `aud` / `exp` rules in section 1.

**Which panel gets which scope.**

| Panel | roots | permissions |
|---|---|---|
| Inspect directory panel (activity bar Inspect View, `logview-view.ts`) | the log directory, `dir` | read, list, write |
| Inspect file panel (`.eval` custom editor, URL handler, terminal link; `logview-editor.ts`, `showLogFile`) | the log file, `file` | read, list, write |
| Host-originated calls (tree listing, tree delete, dist path, app-config) | the exact target | what the call needs (`delete` only for the tree delete command) |

`write` is log editing (`POST /api/log-edit`). `delete` is never granted to a webview panel; the viewer does not delete logs. `list` on a `file` root means "list exactly this file", which the server already renders as a single-entry listing when given a file path (verified in the PR #191 report against `get_logs` and `get_log_files`); the viewer's bootstrap probe needs it.

**Implicit server defaults under a scope.** `/logs`, `/log-files`, `/log-dir`, `/eval-set` and `/flow` substitute `default_dir` when `log_dir` is absent. Under a scope the server's default is never used: with exactly one root, an absent location binds to that root (a `dir` root lists the directory; a `file` root yields the single-file listing), replacing the host-side rewrite PR #191 added (`bindLogProxyDefaultLocation`) with the same observable result. With zero or several roots, an absent location is 403.

## 3. inspect_ai changes

### AccessPolicy stays; a resolver layer wraps it

`AccessPolicy` (`fastapi_server.py`, four `can_*(request, file) -> bool` methods) and `FileMappingPolicy` (`map` / `unmap`) are public in practice: Hawk subclasses both and passes them to `view_server_app(mapping_policy=..., access_policy=...)`. Its access policy receives bucket-relative strings, keys permission on the top-level eval-set folder, and denies `can_list` for `""` and `/`; its mapping policy prepends the S3 base URI. Neither protocol changes: same method names, same signatures, same boolean meaning, same strings.

The canonical-location property is added as a layer the server calls instead of calling the policy directly:

```python
@runtime_checkable
class ResolvingAccessPolicy(Protocol):
    async def resolve_read(self, request: Request, location: str) -> str: ...
    async def resolve_write(self, request: Request, location: str) -> str: ...
    async def resolve_delete(self, request: Request, location: str) -> str: ...
    async def resolve_list(self, request: Request, location: str | None) -> str: ...
```

Each returns the string the route must use for I/O, or raises `HTTPException(403)`. `resolve_list` takes `None` for an absent listing location and decides what that means.

**How the server picks.** `view_server_app` wraps whatever it is given once, at construction:

- If `access_policy` satisfies `ResolvingAccessPolicy` (all four `resolve_*` present), it is used as is. The built-in policies below do.
- Otherwise it is wrapped in `CanonicalizingAdapter(access_policy, default_dir)`.
- If `access_policy` is `None`, the adapter wraps a permit-all policy; `view_server_app(access_policy=None)` keeps meaning "no checks", which embedders may rely on.

**What the adapter does.** For a plain `AccessPolicy` the adapter passes the caller-supplied string, exactly as the routes pass it today, and returns that same string for I/O:

| Step | Today | With the adapter |
|---|---|---|
| String given to `can_*` | `normalize_uri(log)` on the `{log:path}` routes and `/log-headers`; `urllib.parse.unquote(log)` on the pending-sample and log-message routes; `default_dir` when `log_dir` is absent | identical |
| String used for I/O | the same string, through `mapping_policy.map` | identical |
| Denial | 403 | 403 |

The adapter deliberately does no canonicalization. A third-party policy may be keyed on a relative or bucket-relative spelling (Hawk is), and a mapping policy owns the translation to the storage location, so rewriting the string before `can_*` or before `map` would change what such deployments authorize and open. The rule is: the caller-supplied once-decoded string is the contract for plain policies; canonicalization is the job of the built-in resolving policies, which have no mapping policy in front of them. `FileMappingPolicy` is untouched.

The `_validate_*` helpers become `file = await _resolve_read(request, log)` and each of the fourteen location-bearing routes passes the returned value onward, as the #4370 diff did. For a plain policy that value is what the route computed today, so a Hawk deployment observes no change in either token-less or token mode.

**Built-in resolving policies.**

| Policy | Used when | Behaviour |
|---|---|---|
| `OnlyDirAccessPolicy(log_dir)` | standalone, no token | keeps its `can_*` methods (no known caller, but the class is importable) and adds `resolve_*` on `scope.py`, with one `dir` root and all four permissions |
| `ScopedAccessPolicy` | request carries a verified JWT | resolves against `request.state.view_scope`, built from the `inspect_view_scope` claim |
| `UnscopedResolvingPolicy` | request carries the raw master token (legacy credential) | returns the string unchanged (today's behaviour); refused when `--require-scoped-authorization` is set |
| `TokenModeAccessPolicy` | installed by `standalone_view_app` whenever any credential (shared secret or public key) is configured | dispatches per request between the two above on `request.state` |

`standalone_view_app` always installs a policy; the `access_policy=None` branch in token mode disappears. The `--require-scoped-authorization` option (section 1) removes the unscoped row at runtime.

### Embedding contract (unchanged, now stated)

`view_server_app(mapping_policy, access_policy, default_dir, recursive, fs_options, generate_direct_urls)` returns the bare route app with no authentication. An embedder supplies identity by wrapping it in its own middleware and leaving whatever it needs on `request.state`, and supplies authorization through `AccessPolicy` (or `ResolvingAccessPolicy`) and storage mapping through `FileMappingPolicy`, both of which receive the `Request` and can read that state. This is exactly how Hawk is built and nothing in this design changes it: signatures, protocol methods, the meaning of `access_policy=None`, and the strings handed to plain policies all stay as they are (section 5, "Embedders"). `standalone_view_app` is the one place inspect_ai does authentication itself, for `inspect view` and the extension. The `ScopedAccessPolicy` below is structurally a Hawk-style policy: it reads `request.state.view_scope` the way Hawk's reads `request.state.auth`.

### Resolving the scope from the request

`authorization_middleware` is replaced by `ViewAuthorizationMiddleware`, pure ASGI (like `AsyncFilesystemMiddleware`, so state set here reaches the route and its `tg_collect` fan-out). It reads the single `Authorization` header (duplicates are 401, as `_single_header` in `network.py` does for `Host`), classifies it by shape as a JWT (`Bearer ` plus three segments) or the legacy master token, verifies the JWT with the library against the shared secret, `aud = "inspect-view"` and `algorithms=["HS256"]`, builds a `ViewScope` from the `inspect_view_scope` claim, and sets `scope["state"]["view_scope"]` to it or to `None` for the legacy credential. Verified tokens are cached by token string until their `exp`, with a small bound; the extension mints one token per panel per server instance. The middleware is added only by `standalone_view_app`; embedders of `view_server_app` such as Hawk keep their own authentication.

### Canonicalization contract

New `src/inspect_ai/_view/scope.py`, built from #4370's `path_scope.py` (head 0239b55b4). Public surface: `ScopeRoot`, `ViewScope`, `Location`, `scope_from_claims(claims: dict) -> ViewScope` (applies section 2's validation to a verified JWT's claims), `canonical_location(location) -> Location | None`, `resolve_child(base, child)`, `PathScope` (roots plus `resolve(location, permission) -> Location | None`).

Reused from `path_scope.py`:

- `_canonical_local_path`: `split_protocol` to tell `file:` from bare paths; Windows drive detection; `Path.resolve()` so symlinks and missing suffixes resolve through the nearest existing ancestor; backslash and `..` rejection in URI paths.
- `_local_path_from_file_uri`: rejects query, fragment, userinfo and port; rejects a non-`localhost` authority except as a UNC path on Windows; strips the slash before a drive letter.
- `_canonical_remote_path`: lowercases scheme and authority, rejects fragment and userinfo, decodes the path once and rejects `\`, `?`, `#` and `..` in decoded components, normalizes, canonicalizes the query. Directory roots may not carry a query; `http(s)` may not be a directory root. Implementation note (review round 2): before the string canonicalization the location is folded through fsspec's registry the way `main`'s `_strip_protocol`/`unstrip_protocol` did, so scheme aliases (`s3a`→`s3`, `az`/`abfss`→`abfs`, `gcs`→`gs`) and adlfs's `container@account…` authority all canonicalize to the primary spelling; the I/O location for an Azure log is therefore `abfs://container/…` whatever the request spelled, which is also what `view_server` derives for the default directory. The claim schema accepts the aliases as well.
- `_parse_opaque_http_file`: an `http(s)` file root is the exact raw URL, matched byte-for-byte, so signed URLs survive.
- `PathScope.resolve`: file roots match exactly, directory roots match canonical descendants, and the result is the string handed to I/O.

Dropped from `path_scope.py`: the two-header carrier (replaced by the JWT claim); `parse_canonical`'s rule that a host-asserted root is rejected if a symlink now sits there (roots in the token are user spelling; the server canonicalizes them when it parses the token and caches the result with it, since whoever can retarget a symlink at a workspace root already controls a trusted workspace, which `SECURITY.md` places outside the threat model; a deliberate reversal, recorded as such); and the duck-typed `getattr(policy, f"resolve_{op}")` discovery, replaced by the runtime-checkable protocol above.

Added:

- `ViewScope` and `scope_from_claims`, with the validation rules of section 2. No signing or verification code: that is PyJWT's.
- `Location`, the typed result of resolution carrying the canonical string and the root and permission that authorized it. Built-in policies use `location.io_path`; identity comparisons compare `Location`s, never raw strings.
- The decode-once rule, stated in one place: the server percent-decodes a location exactly once after route decoding (`normalize_uri` for `{log:path}` routes and `/log-headers`, `urllib.parse.unquote` for the pending-sample and log-message routes), then treats every remaining character, including `%`, `?` and `#`, as part of a file name. `_canonical_local_path` receives the once-decoded string and never re-parses it as a URI. Finding 4304664 closes by construction: there is no second parser to disagree with. The string given to plain policies is the same once-decoded string, so the rule holds for them too. The listing routes (`/logs`, `/log-files`, `/log-dir`, `/eval-set`, `/flow`) apply no decode of their own to `log_dir`/`dir` beyond the framework's query decoding, exactly as `main` does; the resolver and the I/O see the same string, so nothing is exploitable, and the asymmetry is kept for compatibility rather than being an omission to fix.
- Windows drive-letter case folding for `file:` roots, matching the extension's `getRelativeUri`.
- Bare relative paths resolve against the server's own working directory in the built-in policies and are judged like any other candidate (finding 4363241 was a host-versus-server cwd mismatch).
- `resolve_child(base, child)` replaces the string join in `/eval-set` and `/flow` (`base_dir + "/" + sub_dir.lstrip("/")`): `child` must be relative and free of `..` and backslashes, and the joined string is what the policy sees. This runs before any policy, so it is the one tightening a plain-policy deployment observes: a `dir` value containing `..` is 400 instead of being handed to `can_list`. The viewer never sends one; Hawk's `eval_set_folder` normalizes such values itself today, so no permitted request changes outcome.

`OnlyDirAccessPolicy` on `scope.py` fixes the prefix-sibling and symlink weaknesses of the current `_canonical_uri` / `_validate_log_dir` (`startswith` plus a literal `..` check).

### Advertising support

`AppConfig` in `src/inspect_ai/_view/common.py` gains `scoped_authorization: bool`, true when `standalone_view_app` installed `TokenModeAccessPolicy`, plus `scope_claim: "inspect_view_scope"` so a client can see the claim name; token-less standalone and embedders report false. `GET /api/app-config` is already called by the extension (`getAppConfig()` in `inspect-view-server.ts`), so detection needs no new route.

## 4. Extension changes (Inspect half)

### Mint a scope per panel

New `src/core/package/view-scope.ts`: the `ViewScope` type mirroring section 2, `scopeForLogPanel(type, uri)`, `scopeForHostCall(uri, permissions)`, and `mintScopedToken(masterToken, scope)` using `jose`'s `SignJWT` with HS256, `aud: "inspect-view"`, `sub` set to the panel key, and a one-hour `exp`; tokens are re-minted lazily when within five minutes of expiry. Root URIs are emitted with `Uri.toString(true)` after `Uri.file` for local paths, the spelling `normalize_uri` and `_canonical_local_path` accept.

`PackageViewServer.proxyRpcRequest(request, scope?)` gains an optional scope and `request()` an authorization source: a scope mints and caches a JWT per (server instance, scope JSON) and sends `Authorization: Bearer <jwt>`; no scope sends the master token as today. Panels outside this design pass no scope. Inspect host-originated calls (`evalLogs` for the tree, `evalLogDelete`, `getDistPath`, `getAppConfig`) pass an exact-target scope when the server supports scoped tokens and the master token otherwise. `HttpProxyRpcRequest` and `parseProxyRequest` are unchanged.

`LogviewPanel` computes its scope once in the constructor from `type` and `uri`.

### Attach per request and bypass the Inspect host-side checks when the server enforces scope

The two paths meet at one dispatch point per panel. `LogviewPanel` holds a `confine` function chosen from `server_.scopedAuthorization(instance)` at the time of each request (the flag lives on the `ServerInstance`, section 5):

- Scoped path: `http_request` becomes `server_.proxyRpcRequest(parseProxyRequest(params[0]), this.scope_)`, and the named methods that take a webview-supplied location (`eval_log`, `eval_log_size`, `eval_log_bytes`, `eval_log_headers`, `eval_log_pending_samples`, `eval_log_sample_data`, `log_message`, `edit_log`, `post_search`, `get_search_result`) forward the value unchanged with the panel scope. The server decides.
- Legacy path: exactly today's code. `http_request` runs `parseProxyRequest` then `assertLogProxyInScope` with `logPathInScopeAllowingEncoded`, and the named methods run `requireScope`; the master token is attached.

`parseProxyRequest` runs on both paths. Nothing in `proxy-scope.ts`, `logview-panel.ts` or `uri.ts` is deleted: `requireScope`, `logPathInScope`, `logPathInScopeAllowingEncoded`, `assertLogProxyInScope`, `kLogNoLocation`, `kLogSegmentRoutes`, `bindLogProxyDefaultLocation`, `percentDecodeOnce` and `parseLocationLiterally` stay as the legacy path, and their suites in `logview-panel.test.ts` and `proxy-scope.test.ts` keep running unchanged. `scripts/proxy-routes/check.mjs` keeps checking the Inspect route list against the server's OpenAPI inventory, because the legacy table still has to match old servers. The dispatch is the only new branch; a bug that selects the legacy path against a scoped server costs nothing (the server still enforces), and a bug that selects the scoped path against an old server fails closed, because an old server compares the header to the master token and returns 401 to a JWT.

### What stays

- `parseProxyRequest` (`proxy-request.ts`): the payload-shape contract with the webview, independent of scope.
- Per-panel immutability and recreate-on-scope-change in `logview-view.ts` (`scopeKey`) and the restore-state guard; they now decide which scope is minted.
- `view-server.ts` lifecycle: token per instance, `127.0.0.1` literal, `redirect: "error"`, failed-request isolation from #189.
- `SECURITY.md`'s "The local view server" section: the third property becomes "when the server enforces scope, every forwarded Inspect request carries a JWT minted by the host for that panel; against a server that does not, and for other panels, the host's route table confines each request. A change that adds a pass-through route to that table is still a security change."

### Capability advertisement to the viewer

The Inspect viewer bundle removed its named-RPC fallback in ts-mono #482 (2026-08-04), first shipped in inspect_ai 0.3.253 (fe2bcf83f4, 2026-08-07); since then it refuses to start against a host that does not advertise `http_request`. Advertising `http_request` only when the server supports scoped authorization would therefore blank every panel against inspect_ai 0.3.253 through the last pre-scoped release. Advertisement stays unconditional and the confinement path varies:

| Server | Confinement |
|---|---|
| Reports `scoped_authorization` | none in the host; per-panel JWT on every request |
| Older token-mode server | today's `assertLogProxyInScope` and `requireScope` with the master token |

Both rows are permanent (section 5).

## 5. Rollout and compatibility

Let A be the first inspect_ai release containing section 3 (after 0.3.263) and E the first extension release containing section 4 (after 0.9.19).

**The decided rule (Charles, 2026-09-14).** A new extension must always support an older installed inspect_ai. There is no floor raise and no deletion release. The host-side Inspect confinement is the permanent legacy path; scoped authorization is the primary path whenever the server supports it; the choice is made per server instance.

**Detection.** After each server start the extension calls `GET /api/app-config` with the master token and stores `scoped_authorization` on the `ServerInstance`. Nothing is inferred from a version number: a server that does not report the flag gets the legacy path, whatever its version. The flag is recomputed on every restart, so upgrading or downgrading inspect_ai mid-session switches paths at the next spawn. Until the probe has answered, requests take the legacy path.

**New server, old extension.** The extension sends the master token; the middleware installs `UnscopedResolvingPolicy`; behaviour is identical to today.

**Old server, new extension.** The legacy path runs: `assertLogProxyInScope` and `requireScope` with the master token, as on `main` today. Because this path lives on indefinitely, the open host-side findings remain relevant for old servers. They should still be fixed on the legacy path where the fix is cheap and local: 4331873 is already fixed there by PR #191; 4304664 (refuse a decoded location whose parsed form carries a query or fragment) and 4363242 (decode the child before judging absoluteness in `joinLocation`) are small predicate changes and belong in PR 3; 4363241 (relative locations against the host cwd) is cheap to close by refusing bare relative locations in the predicates, since the viewer never sends them. The legacy suites in `proxy-scope.test.ts` and `logview-panel.test.ts` stay in CI against a fake server that does not advertise the flag, and the scoped suites run against one that does, so both paths are exercised on every change.

**Embedders of `view_server_app`.** Hawk (pins `inspect-ai>=0.3.263`, wraps `view_server_app` and Scout's v2 app with its own OIDC middleware and policies) and any other embedder see no change: their policies are wrapped by the adapter, receive and return the strings they do today, and `scoped_authorization` reports false. The only observable difference is the 400 on a `..`-bearing `dir` value for `/eval-set` and `/flow` (section 3). A CHANGELOG entry states the new optional `ResolvingAccessPolicy` protocol and that plain `AccessPolicy` implementations need no change.

**Retiring the legacy credential.** `--require-scoped-authorization` / `INSPECT_VIEW_REQUIRE_SCOPED_AUTHORIZATION=1` ships in PR 2, default off, and is a general server option rather than an extension hook: any deployment that has migrated its clients can set it. The extension sets the variable only when detection has already succeeded for the same package binary (remembered per `packageBinPath` across restarts, cleared when the interpreter or package changes), never on a first spawn, so an old inspect_ai never sees it; and only once every Inspect host call mints a scope and no panel outside this design still sends the master token. Flipping the server default to required is a later release decision, taken once released clients have had time to migrate; when it flips, an unmigrated client is confined to the startup scope and sees 401s rather than an open server, which is the direction a security default should fail in.

**Standalone browser path.** `inspect view` with no token keeps `OnlyDirAccessPolicy(log_dir)` on `scope.py`; the only visible change is that paths previously accepted through a prefix collision or symlink escape are refused. A JWT against a token-less server is 401. `inspect view bundle` and `embed` run no server and are unaffected.

## 6. Eric's gap

Eric parked #4370 and its sibling PRs within three minutes on 2026-06-27 (22:47 to 22:49 UTC) with the same comment: "After chasing followups, I realized the capability scoping PRs don't fully resolve the issue. Converting this to draft while I work out a better overall approach." No review threads exist on them; the only review is Charles's Codex summary on the extension PR #123 (14:11 UTC). No later approach was published. The gap is not stated; the following is reconstructed and labeled.

**What the record shows, as it bears on inspect_ai and the extension.**

1. Four follow-up commits landed that day (15:34 to 17:39 UTC), each fixing a representation mismatch: symlink identity, the I/O layer using the caller's alias rather than the authorized canonical path, query re-serialization breaking signed URLs, identity checks comparing spellings. The Codex review on #123 found the same family in TypeScript: `realpath` failing on directories that do not exist yet, stale panel scope when only the kind changed, file-scoped views treated as directory-scoped for refresh, `http(s)` files with queries rejected.
2. Between the second and third fix Eric opened issue #484 (repository in the appendix): "sharing only a path-normalization helper is too narrow. The recurring failures come from losing the distinction between user-supplied path spelling, canonical runtime identity, capability proof, and the final I/O representation."
3. That morning he opened ts-mono #373, showing the viewer bundle itself let query parameters, hash routes and window messages choose the log location: a third layer with its own notion of where it may look.

**Inferred gap (assumption, supported by 1 to 3).** The series enforced scope on strings at three layers that each re-parsed and re-resolved them, and a boolean check could not hand the authorized canonical location forward to I/O. Each fix exposed another check/use divergence, and the day ended with a written statement that the abstraction was wrong.

**How this design resolves it.** One canonicalizer, one decode-once rule and one resolver layer whose result is the location used for I/O (section 3); the host no longer parses routes or predicts server decoding, so check and use live in one process. Keeping `AccessPolicy` boolean does not reopen the gap: the built-in policies resolve, and plain policies are given exactly the string that is then opened, which is the property Eric's fixes were chasing. The scope is a typed object with one wire form and a conformance corpus (section 7). Symlink retargeting of a root is judged outside the threat model and handled by per-token resolution rather than #4370's canonical-assertion rule, removing the "missing root" and "retargeted root" failures the Codex review found.

**Not resolved here.** ts-mono #615 (successor of #373): the viewer's own choice of log location. Server enforcement contains the impact (a steered webview gets 403); the viewer-side model is separate work (section 8).

## 7. Verification

**Conformance corpus.** One fixture, `tests/_view/scope_conformance/cases.json`, published with the package as `inspect_ai/_view/scope_conformance.json` so other consumers can load it from the installed inspect_ai and the extension copies it at check-in with a drift check. Each case has a scope payload, a candidate location, a permission and an expected result (`resolved: <canonical>` or `denied`). Cases, from #484's list plus the open findings' payloads: symlinked and retargeted roots (resolve through the current target, recorded as deliberate); missing suffixes; nested symlink escape; exact file containment and a file root refusing parent and siblings; a directory root refusing itself for `read` and admitting itself for `list`; remote scheme and authority boundaries; duplicate separators, `.` and `..`, POSIX backslashes; encoded delimiters after decode-once (`%2F`, `%3F`, `%23`, `%252F`, the 4304664 payloads `file:///w/logs/x#/../../etc/passwd` and `…x%23/../…`, the 4363242 payload `dir=%252Fhome%252Fvictim%252Fother`); bare relative `../x` denied; opaque signed URLs with encoded `&`, `=`, `/`, spaces, duplicates and reordering (exact only); Windows drive and UNC, drive-letter folding; `resolve_child` with absolute, `..`, equal-to-root and strict-descendant children; JWT cases (valid HS256; wrong secret; `alg: none`; an RS256-headed token, refused by the pinned `["HS256"]` list; missing `exp`; expired; wrong `aud`; malformed or missing `inspect_view_scope`; empty `roots`; unknown `v`; `http` root with `kind: dir`; duplicate `Authorization`; unknown claim field accepted; unknown permission ignored).

**Embedder cases**, in `tests/_view/test_view_server.py`, including a Hawk-shaped pair (a mapping policy prepending a base URI, an access policy keyed on the first path segment and reading `request.state`, denying `can_list` for `""` and `/`) driven through the routes with an outer middleware that sets `request.state`, asserting identical accept/deny outcomes and identical strings to `main`: a recording plain `AccessPolicy` receives, for each of the fourteen routes, byte-for-byte the string it receives on `main` today (`normalize_uri`, `unquote`, `default_dir`); the I/O path passed to `mapping_policy.map` is unchanged; `None` listing location yields `default_dir`; a policy that is also a `ResolvingAccessPolicy` is used directly and its `can_*` are never called.

**Route-coverage test.** In `tests/_view/`, enumerate `app.routes` and assert every route is either in an explicit `ROUTES_WITHOUT_LOCATION` set or consulted the resolver: install a recording resolving policy that raises 403 on every call, send each route a syntactically valid location, and assert both a 403 and at least one recorded call. A route in neither set fails with its path, so adding a route forces classification. A static guard scans `fastapi_server.py` for `normalize_uri(` and `unquote(` outside the resolver helpers, on the model of `test_no_bare_click_exit_in_ctl_error_sites`.

**Extension tests.** Drive `LogviewPanel` through JSON-RPC against a fake server that advertises scoped authorization; assert the JWT on the wire verifies with the test secret and its `inspect_view_scope` claim equals the expected scope for each panel type, that host-originated calls carry exact-target scopes, and that no request carries the master token. Against a fake server without the flag, the existing legacy suites run unchanged.

**Findings closed.** Of the nine open hostile-log-via-webview findings in the 2026-09-14 export, this design closes:

| Finding | Title (abbreviated) | Closed by |
|---|---|---|
| 4304664 MEDIUM | `#`/`?` suffix in raw string carries `..` past the parsed-URI check | log half: the decode-once rule (section 3) |
| 4363242 LOW | Child absoluteness judged before the predicate's percent-decode | `/eval-set` and `/flow`: `resolve_child` |
| 4363241 LOW | Relative locations resolved against the extension host cwd | log half: one cwd |
| 4331873 LOW | File-scoped log panel lists the server default via proxy | default binding to the sole root (section 2); PR #191's host-side fix becomes server-side |

The other five, and the non-log halves of the first three, are outside this design and listed in the appendix. Not in this class: 3731839 (command-file IPC) and 4363105 (tree-id collision). 4304297 was fixed by #191; its host-side predicate is deleted by section 4 without changing the outcome.

## 8. Out of scope, stated

- Everything in the appendix.
- Command-file IPC (finding 3731839): separate cancelled work, see `Repo-data/meridianlabs-ai/inspect_vscode/evidence/command-file-ipc-2026-09-10/handoff.md`.
- Viewer XSS hardening and a script CSP for the browser viewers: follow-up in ts-mono and the extension's `getWebviewPanelHtml`.
- Viewer-side log-location authority (ts-mono #615).
- Workspace-trust-class findings and the tree-id collision (4363105).
- Any change to `AccessPolicy`, `FileMappingPolicy` or the `view_server_app` signature beyond the new optional protocol.

## 9. Implementation plan

| # | Repo | PR | Depends on | Size | Lands independently? |
|---|---|---|---|---|---|
| 1 | inspect_ai | `scope.py` (canonicalizer, `ViewScope`, `Location`, `scope_from_claims`); `ResolvingAccessPolicy` protocol and `CanonicalizingAdapter`; routes call the resolver layer; `OnlyDirAccessPolicy` gains `resolve_*` on the new canonicalizer; default-binding rule; `resolve_child` for eval-set/flow; conformance corpus, adapter cases, route-coverage test. Token mode still installs `UnscopedResolvingPolicy`. Supersedes #4370's path work. | none | L (~950) | Yes; standalone containment tightens, embedders unchanged. |
| 2 | inspect_ai | `ViewAuthorizationMiddleware` verifying HS256 bearer JWTs against the shared secret (`aud` fixed, `exp` required, `algorithms=["HS256"]`), `ScopedAccessPolicy`, `TokenModeAccessPolicy`, `--require-scoped-authorization` (default off), `AppConfig.scoped_authorization` / `scope_claim`, mounted search router under the resolver (appendix); one JWT library dependency (HS256 only). Docstring for the embedding contract on `view_server_app`. | 1 | M (~350) | Yes; existing clients send the master token and take the legacy path. |
| 3 | inspect_vscode | `view-scope.ts` minting with `jose` (new dependency); `proxyRpcRequest(request, scope?)`; per-panel Inspect scopes; per-instance detection via app-config; one dispatch point selecting the scoped or legacy path; named methods forward with scope on the scoped path; legacy path untouched and kept permanently; cheap legacy-path fixes for 4304664, 4363242 and 4363241; `SECURITY.md` update. No deletions, no floor change. | 2 released (A) | M (~550 net) | No; needs A for the scoped path end to end. The legacy-path fixes can be split out and land first. |

PRs 1 and 2 can be one PR if review bandwidth prefers; they are split so the resolver layer and standalone containment can be reviewed without the protocol change. PR 1's review should include running Hawk's policy tests (`hawk/tests/api/test_server_policies.py`, `test_eval_log_server.py`) against the branch, or a local equivalent that subclasses `AccessPolicy` and `FileMappingPolicy` the way Hawk does. PR 3's tests must run every existing legacy suite against a fake server without the flag and the new scoped suite against one with it. Each PR follows the repository rules: `Fixes` to the accepted issue (one per repository, to be filed), a CHANGELOG entry for the user-visible change, `make check` and `make test`, two fresh review passes for all three PRs, and `--runtrio` for PR 2's middleware. Flipping the default of `--require-scoped-authorization` is a separate, later release decision and not a PR in this plan.

## 10. Decisions

All decisions were taken by Charles on 2026-09-14 and are recorded in `decisions.md` alongside this document.

| Decision | Answer | Where applied |
|---|---|---|
| Rollout: must a new extension support an older installed inspect_ai? | Yes, always. No floor raise, no deletion release. The host-side Inspect confinement is the permanent legacy path, selected per server instance by app-config detection. | sections 4, 5, 9 |
| Scope carrier | Reopened and re-decided late on 2026-09-14: a standard bearer JWT, HS256 with the existing shared secret, scope in the `inspect_view_scope` claim. The earlier custom `InspectScope` token was withdrawn because the model must be one any client can adopt with stock tooling. | sections 1, 2, 3 |
| Identity-provider deployments | No public-key or JWKS options in inspect_ai. Such deployments embed `view_server_app` behind their own middleware and policies, as METR's Hawk already does; that contract is unchanged and documented. | sections 1, 3, 5 |
| General model | The server always has a scope: startup scope without a credential, the claimed scope with a verified JWT, today's unscoped behaviour only for the legacy master token, which a server option can refuse. New extension against an old server retains today's behaviour exactly. | sections 1, 5 |
| Accepted issues for the contribution policy | One per repository: inspect_ai and inspect_vscode, referencing this design. CASE files them after this design is final. | section 9 |
| Supersede comment on #4370 | Posted only after the first implementation PR exists, crediting Eric and linking the PR. No comment on #482 or #483. | section 9, appendix |

Earlier decisions in the same day narrowed the scope to inspect_ai and the Inspect half of the extension (Scout to the appendix) and preserved the `AccessPolicy` and `FileMappingPolicy` protocols for existing implementers (section 3).

## Appendix: future Scout adoption

Scout (meridianlabs-ai/inspect_scout, and the Scout half of the extension) is out of scope for this design. Scout panels keep today's host-side confinement exactly as on `main`: `assertScanProxyInScope` in `proxy-scope.ts`, `scanLocationInScope` and `scanLocationInScopeAllowingEncoded` in `scanview-panel.ts`, and the live `setScanResultsScope` / `setTranscriptsScope` readers. Scout requests continue to carry the master token. Eric's Scout PRs #482 (network hardening) and #483 (startup capabilities) are left as they are. Issue #484, quoted in section 6, is meridianlabs-ai/inspect_scout#484.

**Wire-contract constraints kept for Scout.** The JWT credential, the `inspect_view_scope` claim schema and the public surface of `scope.py` (section 3) are shared. Scout would import `scope.py` from inspect_ai (Scout already depends on inspect_ai and its development branch pins inspect_ai `main`) and keep its own policy wrappers local. Nothing inspect_ai ships changes when Scout adopts it, and no `v` bump is needed, because of the reserved fields below.

**Reserved claim fields.** The `inspect_view_scope` claim may carry three more fields, all optional:

```json
{
  "transcripts": [{"uri": "s3://team/transcripts", "kind": "dir"}],
  "project": {"uri": "file:///w/proj", "permissions": ["read", "write", "delete"]},
  "actions": ["start-scan", "project-config-write"]
}
```

`transcripts` are directory roots for Scout transcript sources (implicitly read and list). `project` is the Scout project directory, governing validation files and project configuration. `actions` gate Scout's two mutating routes whose bodies carry locations. The inspect_ai server today validates their shape (a malformed `transcripts` entry or `kind` is 401, matching `roots`), accepts a payload whose `roots` is empty when `project` is present, and ignores all three for authorization. Unknown permission strings, unknown actions and unknown fields inside the claim are ignored. The extension's `view-scope.ts` emits them empty.

**Scout embedding.** Hawk wraps Scout's `inspect_scout._view._api_v2` app with its own middleware and path handling (`hawk/api/scan_view_server.py`). A future Scout adoption should keep that app embeddable with a policy hook rather than forcing Scout's own authentication on embedders.

**The Scout search router mounted in inspect_ai.** `view_server_app` mounts `create_search_router()` from `inspect_scout._view._api_v2_search` under `/scout` with no policy. This is inspect_ai code and is brought under the resolver layer in PR 2 with #4370's router dependency: `_validate_scout_route_scope` decodes `request.path_params["dir"]` (strict base64url: the decoded value must re-encode to the received segment, else 400), calls `_resolve_read`, and re-encodes the result into `path_params`. The two routes carrying a directory are `POST /scout/transcripts/{dir}/{id}/search` and `GET /scout/transcripts/{dir}/{id}/searches/{search_id}`; `GET /scout/searches` carries none. Hawk removes these routes by path prefix and mounts its own (`eval_log_server.py`); the dependency is attached to the routes, so that filter keeps working. If Scout later accepts a resolver argument, inspect_ai can pass one and the dependency becomes the fallback. Note that the search `POST` does not carry inspect_ai's mutating-request guard (`X-Inspect-View-Request`, `Sec-Fetch-Dest`), as on `main`; that belongs with Scout's body validation (finding 4304662) rather than with this design.

**Scout-side findings left open** (from the nine open hostile-log-via-webview findings in the 2026-09-14 export):

| Finding | Title (abbreviated) | Note |
|---|---|---|
| 4304662 HIGH | Scan proxy forwards startscan/project-config bodies unchecked | needs Scout body validation under `start-scan` / `project-config-write` |
| 4363639 MEDIUM | Validations routes pass through with no host-side check | needs the `project` grant on the Scout server |
| 4363699 LOW | Single-scan editor lists the server's default results directory | needs Scout default binding |
| 4304299 LOW | Scan editor scope is the whole parent directory | needs Scout server support for the narrowed listing |
| 4304661 LOW | Scan-view legacy named methods check encoded, server decodes | the extension's `get_scans`, `get_scan`, `get_scanner_dataframe*` call routes Scout removed in #256 (first absent in 0.3.41) and the Scout viewer bundle uses `http_request` exclusively; deleting them with `ScoutViewServer.legacy` is an extension-only change that breaks nothing that works today and would close this finding. Assumption: no user runs a Scout older than 0.3.41 with the current extension. Not part of this design's PRs; recorded here for the Scout phase. |
| 4304664, 4363242, 4363241 | (scan halves) | the scan-view predicates and the `/api/v2/scans/<dir>/<scan>` join stay host-side until Scout adopts the contract |
