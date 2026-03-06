# Inspect Log Viewer

React tools for viewing eval logs produced by [Inspect-AI](https://inspect.aisi.org.uk/).

## Installation

```bash
npm install @meridianlabs/log-viewer
```

## CSS Requirements

The log viewer requires CSS styles to display correctly. Import the bundled styles:

```typescript
import "@meridianlabs/log-viewer/styles/index.css";
```

This includes all required dependencies (Bootstrap, Bootstrap Icons, Prism.js themes).

### Example Usage

```tsx
import { useEffect, useState } from "react";
import {
    App as InspectApp,
    createViewServerApi,
    clientApi,
    initializeStore,
    ClientAPI,
    Capabilities,
} from "@meridianlabs/log-viewer";
import "@meridianlabs/log-viewer/styles/index.css";

export function App() {
    const [api, setApi] = useState<ClientAPI | null>(null);

    useEffect(() => {
        async function initializeApi() {
            // Get log directory from URL parameter
            const urlParams = new URLSearchParams(window.location.search);
            const logDir = urlParams.get("log_dir");

            if (!logDir) {
                console.error("Missing log_dir URL parameter");
                return;
            }

            // Create API instance
            const viewServerApi = createViewServerApi({
                // optional params
                logDir: logDir,
                apiBaseUrl: "https://mycompany.com/api",
            });
            const clientApiInstance = clientApi(viewServerApi);

            // Set up capabilities and storage
            const capabilities: Capabilities = {
                downloadFiles: true,
                webWorkers: true,
                streamSamples: true,
                streamSampleData: true,
                nativeFind: false,
            };

            // Initialize store and set API
            initializeStore(clientApiInstance, capabilities, undefined);
            setApi(clientApiInstance);
        }

        initializeApi();
    }, []);

    if (!api) {
        return <div>Loading...</div>;
    }

    return <InspectApp api={api} />;
}
```

## Developing

The Inspect log viewer is built into a bundled JS file using `vite`. For users who clone or install from the repo directly, we keep a bundled version committed in the `dist` folder. **When you make changes, your commits/PRs must include updates to the bundled files in the `dist` folder as well as the source code changes.**

### Before You Commit:

Run these commands in the `src/inspect_ai/_view/www` directory:

1. **Lint code:**

    ```bash
    yarn lint
    ```

    Fix any errors reported.

2. **Format code:**

    ```bash
    yarn prettier:write
    ```

3. **Build for library distribution:**

    ```bash
    yarn build:lib
    ```

4. **Build bundled output for the `dist` directory:**
    ```bash
    yarn build
    ```
    Don't forget to stage newly updated changes in the `dist` folder.

You may optionally set the `VIEW_SERVER_API_URL` environment variable at build time to use an API server running on a different host.