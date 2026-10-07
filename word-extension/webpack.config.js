const devCerts = require("office-addin-dev-certs");
const CopyWebpackPlugin = require("copy-webpack-plugin");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const webpack = require("webpack");

const urlDev = "https://localhost:3000/";
const urlProd = process.env.BASE_URL || "https://word-addin-plum.vercel.app/";
const originDev = urlDev.replace(/\/$/, "");
const originProd = urlProd.replace(/\/$/, "");

async function getHttpsOptions() {
  const httpsOptions = await devCerts.getHttpsServerOptions();
  return { ca: httpsOptions.ca, key: httpsOptions.key, cert: httpsOptions.cert };
}

module.exports = async (env, options) => {
  const dev = options.mode === "development";
  const config = {
    devtool: "source-map",
    entry: {
      polyfill: ["core-js/stable", "regenerator-runtime/runtime"],
      taskpane: {
        import: ["./src/taskpane/index.tsx", "./src/taskpane/taskpane.html"],
        dependOn: "polyfill",
      },
      commands: {
        import: "./src/commands/commands.ts",
        dependOn: "polyfill",
      },
    },
    output: {
      clean: true,
      chunkFilename: dev ? "[id].chunk.js" : "[id].[contenthash].chunk.js",
    },
    optimization: {
      splitChunks: {
        chunks: "all",
        minSize: 500000, // Increased to avoid too many small chunks
        maxInitialRequests: 5, // Limit number of initial chunks
        // Don't set maxSize at top level to prevent unwanted splitting
        cacheGroups: {
          default: false,
          vendors: false,
          // Vendor chunk for React (highest priority) - don't split
          reactVendor: {
            name: "react-vendor",
            test: /[\\/]node_modules[\\/](react|react-dom)[\\/]/,
            priority: 30,
            reuseExistingChunk: true,
            enforce: true,
            chunks: "all",
          },
          // Vendor chunk for Fluent UI - keep as single chunk, prevent splitting
          fluentui: {
            name: "fluentui",
            test: /[\\/]node_modules[\\/]@fluentui[\\/]/,
            priority: 25,
            reuseExistingChunk: true,
            enforce: true,
            chunks: "all",
            // Prevent splitting by not setting maxSize
          },
          // Vendor chunk for other node_modules (exclude react and fluentui via negative lookahead)
          vendor: {
            name: "vendor",
            // Use negative lookahead to exclude react, react-dom, and @fluentui
            test: /[\\/]node_modules[\\/](?!(react|react-dom|@fluentui))[^\\/]+[\\/]/,
            priority: 10,
            reuseExistingChunk: true,
            minChunks: 2,
            chunks: "all",
          },
        },
      },
      // Enable minification in production
      minimize: !dev,
      // Module concatenation for better tree shaking
      concatenateModules: !dev,
      // Tree shaking
      usedExports: true,
      sideEffects: false,
    },
    resolve: {
      extensions: [".ts", ".tsx", ".html", ".js"],
    },
    module: {
      rules: [
        {
          test: /\.ts$/,
          exclude: /node_modules/,
          use: {
            loader: "babel-loader",
          },
        },
        {
          test: /\.tsx?$/,
          exclude: /node_modules/,
          use: ["ts-loader"],
        },
        {
          test: /\.html$/,
          exclude: /node_modules/,
          use: "html-loader",
        },
        {
          test: /\.(png|jpg|jpeg|ttf|woff|woff2|gif|ico)$/,
          type: "asset/resource",
          generator: {
            filename: "assets/[name][ext][query]",
          },
        },
      ],
    },
    plugins: [
      new HtmlWebpackPlugin({
        filename: "taskpane.html",
        template: "./src/taskpane/taskpane.html",
        chunks: ["polyfill", "taskpane"],
        chunksSortMode: "manual",
      }),
      new CopyWebpackPlugin({
        patterns: [
          {
            from: "assets/*",
            to: "assets/[name][ext][query]",
          },
          {
            from: "manifest*.xml",
            to: "[name]" + "[ext]",
            transform(content) {
              if (dev) {
                return content;
              } else {
                return content
                  .toString()
                  .split(urlDev)
                  .join(urlProd)
                  .split(originDev)
                  .join(originProd);
              }
            },
          },
        ],
      }),
      new HtmlWebpackPlugin({
        filename: "commands.html",
        template: "./src/commands/commands.html",
        chunks: ["polyfill", "commands"],
      }),
      new webpack.DefinePlugin({
        "process.env.REACT_APP_API_BASE_URL": JSON.stringify(
          process.env.REACT_APP_API_BASE_URL || ""
        ),
        "process.env.REACT_APP_API_AUTH_TOKEN": JSON.stringify(
          process.env.REACT_APP_API_AUTH_TOKEN || ""
        ),
        "process.env.AUTODRAFT_FORCE_NON_STREAMING": JSON.stringify(
          process.env.AUTODRAFT_FORCE_NON_STREAMING || "0"
        ),
        "process.env.APP_VERSION": JSON.stringify(require("./package.json").version),
        "process.env.BUILD_TIMESTAMP": JSON.stringify(new Date().toISOString()),
      }),
      new webpack.ProvidePlugin({
        Promise: ["es6-promise", "Promise"],
        process: "process/browser",
      }),
    ],
    devServer: {
      hot: false,
      client: {
        // Office.js is loaded from Microsoft's origin. WebKit can surface a
        // cross-origin exception only as "Script error", which webpack's
        // runtime overlay cannot diagnose. Keep compile errors visible but
        // route runtime failures to AutoDraft's console diagnostics instead.
        overlay: { errors: true, warnings: false, runtimeErrors: false },
      },
      // Disable gzip compression — it buffers SSE responses entirely until
      // the stream closes, which defeats `/api/documents/identify-variables-stream`.
      compress: false,
      headers: {
        "Access-Control-Allow-Origin": "*",
      },
      server: {
        type: "https",
        options:
          env.WEBPACK_BUILD || options.https !== undefined
            ? options.https
            : await getHttpsOptions(),
      },
      port: process.env.npm_package_config_dev_server_port || 3000,
      proxy: [
        // Proxy logger requests to frontend logger server (port 3002)
        {
          context: ["/api/logger"],
          target: "http://127.0.0.1:3002",
          pathRewrite: {
            "^/api/logger": "/logs", // Rewrite /api/logger to /logs
          },
          changeOrigin: true,
          secure: false,
          logLevel: "debug",
        },
        // Proxy all other /api requests to backend (port 3001)
        {
          context: ["/api"],
          target: "http://127.0.0.1:3001",
          changeOrigin: true,
          secure: false,
          logLevel: "debug",
          // 5 min for large OOXML upload (PUT /api/templates/:id/content)
          proxyTimeout: 300000,
          timeout: 300000,
          onProxyReq: (proxyReq, req, _res) => {
            const green = "\x1b[32m";
            const reset = "\x1b[0m";
            const timestamp = new Date().toISOString();
            console.log(`${green}✅ [PROXY] ${timestamp}${reset}`);
            console.log(`${green}   📤 API CALL INITIATED${reset}`);
            console.log(`${green}   Method: ${req.method}${reset}`);
            console.log(`${green}   Path: ${req.url}${reset}`);
            console.log(`${green}   Target: http://127.0.0.1:3001${req.url}${reset}`);
            console.log(`${green}   ─────────────────────────────────────────────${reset}`);
          },
          onProxyRes: (proxyRes, req, _res) => {
            const green = "\x1b[32m";
            const reset = "\x1b[0m";
            const timestamp = new Date().toISOString();
            const statusCode = proxyRes.statusCode;
            const isSuccess = statusCode >= 200 && statusCode < 300;

            if (isSuccess) {
              console.log(`${green}✅ [PROXY] ${timestamp}${reset}`);
              console.log(`${green}   📥 API RESPONSE RECEIVED (SUCCESS)${reset}`);
              console.log(
                `${green}   Status: ${statusCode} ${proxyRes.statusMessage || ""}${reset}`
              );
              console.log(`${green}   Path: ${req.url}${reset}`);
              console.log(`${green}   ─────────────────────────────────────────────${reset}`);
            } else {
              const yellow = "\x1b[33m";
              console.log(`${yellow}⚠️  [PROXY] ${timestamp}${reset}`);
              console.log(`${yellow}   📥 API RESPONSE RECEIVED (WARNING)${reset}`);
              console.log(
                `${yellow}   Status: ${statusCode} ${proxyRes.statusMessage || ""}${reset}`
              );
              console.log(`${yellow}   Path: ${req.url}${reset}`);
              console.log(`${yellow}   ─────────────────────────────────────────────${reset}`);
            }
          },
          onError: (err, req, _res) => {
            const red = "\x1b[31m";
            const reset = "\x1b[0m";
            const timestamp = new Date().toISOString();
            console.error(`${red}❌ [PROXY ERROR] ${timestamp}${reset}`);
            console.error(`${red}   💥 Failed to proxy request${reset}`);
            console.error(`${red}   Path: ${req.url}${reset}`);
            console.error(`${red}   Error: ${err.message}${reset}`);
            console.error(`${red}   ─────────────────────────────────────────────${reset}`);
          },
        },
      ],
    },
  };

  return config;
};
