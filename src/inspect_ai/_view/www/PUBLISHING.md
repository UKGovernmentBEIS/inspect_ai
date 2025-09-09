# Publishing Guide for @meridianlabs/log-viewer

This document explains how to test and publish the log viewer package.

## Testing Publishing with Verdaccio

Before publishing to npmjs, you can test the publishing process using the GitHub Action that publishes to Verdaccio (a local npm registry).

### How to run the test:

1. Go to the **Actions** tab in the GitHub repository
2. Find the workflow named "Test Publish to Verdaccio"
3. Click **Run workflow**
4. Optionally enable debug logging for more detailed output
5. Click **Run workflow** to start the test

### What the workflow does:

1. **Environment Setup**: Sets up Node.js and installs dependencies
2. **Verdaccio Setup**: Starts a local npm registry for testing
3. **Quality Checks**: Runs TypeScript, linting, and tests
4. **Build**: Creates the library bundle using `yarn build:lib`
5. **Publish**: Publishes the package to the local Verdaccio registry
6. **Verification**: 
   - Installs the published package in a test project
   - Tests that all exports are available
   - Verifies TypeScript definitions work correctly

### Expected output:

If successful, you should see:
- ✅ All quality checks pass
- ✅ Package builds successfully
- ✅ Package publishes without errors
- ✅ Package can be installed and imported
- ✅ TypeScript definitions are working

## Publishing to npmjs

Once the Verdaccio test passes, you can publish to npmjs:

1. **Update version** in `package.json` if needed
2. **Ensure you're authenticated** to npm: `npm login`
3. **Remove GitHub package config** temporarily:
   ```bash
   # Remove the publishConfig section from package.json
   ```
4. **Build the package**: `yarn build:lib`
5. **Publish**: `npm publish`

## Package Structure

The published package includes:
- `lib/index.js` - Main ES module export
- `lib/index.d.ts` - TypeScript definitions
- All dependencies properly configured as externals (React, React DOM)

## Main Exports

The package exports:
- `App` - Main React component
- `api` - Default API client
- `clientApi` - Client API utilities
- Various types and utilities for working with inspect_ai logs