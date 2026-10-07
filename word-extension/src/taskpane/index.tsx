import * as React from "react";
import { createRoot } from "react-dom/client";
import App from "./components/App";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { API_BASE_URL } from "../services/config";
import { initializeOfficeAuthentication } from "../services/authService";
import { error as logError } from "../services/logger";

const rootElement: HTMLElement | null = document.getElementById("container");
const root = rootElement ? createRoot(rootElement) : undefined;
let officeReadySettled = false;

function renderTaskpaneStatus(title: string, message: string) {
  root?.render(
    <FluentProvider theme={webLightTheme}>
      <div style={{ padding: 20, fontFamily: "system-ui" }}>
        <h2>{title}</h2>
        <p>{message}</p>
      </div>
    </FluentProvider>
  );
}

renderTaskpaneStatus("Loading AutoDraft", "Waiting for Microsoft Word to initialize the add-in.");

// Surface real runtime failures inside the Office webview instead of only the
// generic webpack "Script error" overlay. Route diagnostics through the
// privacy-safe logger so document values and credentials are not serialized.
window.addEventListener("error", (event) => {
  const location = event.filename
    ? `${event.filename.split("/").pop() || "script"}:${event.lineno || 0}:${event.colno || 0}`
    : "unknown-script";
  logError(`[Runtime] uncaught error at ${location}`, event.error);
});

window.addEventListener("unhandledrejection", (event) => {
  logError("[Runtime] unhandled promise rejection", event.reason);
});


window.addEventListener("autodraft-auth-required", () => {
  renderTaskpaneStatus(
    "AutoDraft session expired",
    "Reopen the task pane to sign in again with your Microsoft account."
  );
});

/* Authenticate before rendering production data-bearing UI. */
async function bootstrapAutoDraft() {
  officeReadySettled = true;
  try {
    await initializeOfficeAuthentication(API_BASE_URL);
    root?.render(
      <FluentProvider theme={webLightTheme}>
        <App />
      </FluentProvider>
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    renderTaskpaneStatus(
      "AutoDraft sign-in required",
      `${message} Close and reopen the task pane after your Microsoft account has been provisioned for AutoDraft.`
    );
  }
}

const officeApi = (globalThis as any).Office;
if (officeApi?.onReady) {
  window.setTimeout(() => {
    if (!officeReadySettled) {
      renderTaskpaneStatus(
        "AutoDraft is still loading",
        "Word has not finished initializing the add-in. Close and reopen the task pane, or restart the local dev server."
      );
    }
  }, 10000);
  officeApi.onReady(bootstrapAutoDraft);
} else {
  renderTaskpaneStatus(
    "AutoDraft could not load Office.js",
    "The Microsoft Office JavaScript API was not available in this task pane. Restart Word and reopen AutoDraft."
  );
}

if ((module as any).hot) {
  (module as any).hot.accept("./components/App", () => {
    const NextApp = require("./components/App").default;
    root?.render(
      <FluentProvider theme={webLightTheme}>
        <NextApp />
      </FluentProvider>
    );
  });
}
