# @inspect-ai/log-viewer

A React library for viewing and interacting with Inspect AI evaluation logs.

## Installation

```bash
npm install @inspect-ai/log-viewer
# or
yarn add @inspect-ai/log-viewer
```

## Usage

### Basic App Component

```tsx
import { App, api, initializeStore } from '@inspect-ai/log-viewer';
import '@inspect-ai/log-viewer/lib/style.css';

// Initialize the store with API and capabilities
const capabilities = {
  downloadFiles: true,
  webWorkers: true,
  streamSamples: true,
  streamSampleData: true,
  nativeFind: true,
};

initializeStore(api, capabilities, storage);

// Render the app
function MyLogViewer() {
  return <App api={api} />;
}
```

### Individual Components

```tsx
import {
  Card,
  CardHeader,
  CardBody,
  Modal,
  MarkdownDiv,
  JSONPanel,
  ChatView
} from '@inspect-ai/log-viewer';

function MyComponent() {
  return (
    <Card>
      <CardHeader label="Sample Log" />
      <CardBody>
        <MarkdownDiv markdown="# Hello World" />
      </CardBody>
    </Card>
  );
}
```

### API Usage

```tsx
import {
  api,
  browserApi,
  simpleHttpApi,
  clientApi
} from '@inspect-ai/log-viewer';

// Use the default resolved API
const logs = await api.get_log_paths();

// Or create a custom API
const customApi = clientApi(simpleHttpApi('/path/to/logs'));
const summary = await customApi.get_log_summary('log.eval');
```

## Available Exports

### Components
- `App` - Main application component
- `Card`, `CardHeader`, `CardBody`, `CardCollapsingHeader` - Card components
- `Modal`, `LargeModal` - Modal dialogs
- `MarkdownDiv` - Markdown renderer with LaTeX support
- `JSONPanel` - JSON viewer
- `ChatView`, `ChatMessage` - Chat interface components
- `SampleDisplay`, `SampleSummaryView` - Sample viewing components
- And many more UI components...

### API
- `api` - Default resolved API instance
- `clientApi` - API factory function
- `browserApi`, `simpleHttpApi`, `vscodeApi` - API implementations
- `openRemoteLogFile` - Remote file handling

### State Management
- `initializeStore` - Initialize the application store
- `useStore` - Hook to access store state
- `storeImplementation` - Direct store access

### Types
- `ClientAPI`, `LogViewAPI` - API interfaces
- `EvalSummary`, `LogContents`, `SampleSummary` - Data types
- `StoreState` - Store state type
- And many more TypeScript types...

## Development

### Building the Library

```bash
yarn build:lib
```

### Building the App

```bash
yarn build:app
```

### Development

```bash
yarn dev
```

## Publishing

The library is automatically published to GitHub Packages when changes are pushed to the main branch or when a release is created.

### Manual Publishing

Note: The `.npmrc` file contains a reference to `${NODE_AUTH_TOKEN}` which needs to be set as an environment variable for publishing:

```bash
export NODE_AUTH_TOKEN=your_github_token
yarn publish
```

## License

MIT
