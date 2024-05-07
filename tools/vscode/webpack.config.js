//@ts-check

'use strict';

const path = require('path');

//@ts-check
/** @typedef {import('webpack').Configuration} WebpackConfig **/

/** @type WebpackConfig */
const baseConfig = {
  mode: "none", // this leaves the source code as close as possible to the original (when packaging we set this to 'production')
  externals: {
    vscode: "commonjs vscode", // the vscode-module is created on-the-fly and must be excluded. Add other modules that cannot be webpack'ed, 📖 -> https://webpack.js.org/configuration/externals/
    // modules added here also need to be added in the .vscodeignore file
  },
  resolve: {
    // support reading TypeScript and JavaScript files, 📖 -> https://github.com/TypeStrong/ts-loader
    extensions: [".ts", ".js", ".css"],
  },
  devtool: "nosources-source-map",
  infrastructureLogging: {
    level: "log", // enables logging required for problem matchers
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'ts-loader'
          }
        ]
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader']
      }
    ]
  },
};

/** @type WebpackConfig */
const extensionConfig = {
  ...baseConfig,
  target: 'node', // VS Code extensions run in a Node.js-context 📖 -> https://webpack.js.org/configuration/node/


  entry: './src/extension.ts', // the entry point of this extension, 📖 -> https://webpack.js.org/configuration/entry-context/
  externals: ["vscode"],
  output: {
    // the bundle is stored in the 'dist' folder (check package.json), 📖 -> https://webpack.js.org/configuration/output/
    path: path.resolve(__dirname, 'dist'),
    filename: 'extension.js',
    libraryTarget: 'commonjs2'
  },
};

// Config for webview source code (to be run in a web-based context)
/** @type WebpackConfig */
const envWebviewConfig = {
  ...baseConfig,
  target: ["web", "es2020"],
  entry: "./src/providers/activity-bar/webview/env-config-webview.ts",
  experiments: { outputModule: true },
  output: {
    path: path.resolve(__dirname, "out"),
    filename: "env-config-webview.js",
    libraryTarget: "module",
    chunkFormat: "module",
  },
  performance: {
    // Increase the size limit to 1 MB (or any value you prefer)
    maxAssetSize: 1000000, // in bytes
    maxEntrypointSize: 1000000, // in bytes
  }
};

const taskHyperparamWebviewConfig = {
  ...baseConfig,
  target: ["web", "es2020"],
  entry: "./src/providers/activity-bar/webview/task-config-webview.ts",
  experiments: { outputModule: true },
  output: {
    path: path.resolve(__dirname, "out"),
    filename: "task-config-webview.js",
    libraryTarget: "module",
    chunkFormat: "module",
  },
  performance: {
    // Increase the size limit to 1 MB (or any value you prefer)
    maxAssetSize: 1000000, // in bytes
    maxEntrypointSize: 1000000, // in bytes
  }
};



module.exports = [extensionConfig, envWebviewConfig, taskHyperparamWebviewConfig];