import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowSync24Filled,
  CheckmarkCircle24Filled,
  ChevronDown24Regular,
  ChevronUp24Regular,
  DocumentSquare24Regular,
  ShieldError24Regular,
  CalendarClock24Regular,
} from "@fluentui/react-icons";
import * as React from "react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import TemplateSelector, { Template } from "./TemplateSelector";
import DraftSourceSelector, { DraftSourceMode } from "./DraftSourceSelector";

const TemplateCreationForm = lazy(() => import("./TemplateCreationForm"));
const FormFilling = lazy(() => import("./FormFilling"));
const DocumentSummary = lazy(() => import("./DocumentSummary"));
const RiskAssessment = lazy(() => import("./RiskAssessment"));
const DeadlineTimeline = lazy(() => import("./DeadlineTimeline"));
const DraftingWorkspace = lazy(() => import("./DraftingWorkspace"));

import {
  AiRetryExhaustedException,
  AiServiceException,
  AiTimeoutException,
  identifyVariables,
  identifyVariablesStreaming,
  identifyVariablesViaJob,
  supportsResponseStreaming,
} from "../../services/aiVariableService";
import {
  cleanAccumulated,
  clearAllContentControls,
  extractColoredTextVariables,
  extractDocumentContent,
  getContentControlsInDocumentOrder,
  getReusableTemplateBodyOoxml,
  insertOoxmlIntoDocument,
  readAllContentControlValues,
  renameContentControlTag,
  setContentControlTitleByTag,
  updateVariableInDocument,
} from "../../services/documentExtraction";
import { wrapVariablesWithBindingPlan } from "../../services/wrappingPipeline";
import { syncAutoDraftBindingManifest } from "../../services/documentManifest";
import { error as logError, info, log, warn } from "../../services/logger";
import {
  TemplateServiceException,
  addTemplateVariable,
  clearVariableValues,
  createTemplate,
  getTemplate,
  getTemplateContent,
  listTemplates,
  saveVariableValues,
  updateTemplateContent,
  updateTemplateMetadata,
  deleteTemplate,
  duplicateTemplate,
  updateVariable,
} from "../../services/templateService";
import type { TemplateMetadata, VariableIdentificationResponse, Variable, VerificationReport } from "../../services/types";
import { verifyFinalDocument } from "../../services/autodraftWorkspaceService";
import { reconcileAutoDraftDocument } from "../../services/word/reconciliationService";
import { startBindingEventMonitoring } from "../../services/word/eventService";
import { assertDocumentTextIsUnicodeSafe } from "../../services/documentDiagnosticsService";

const APP_VERSION = process.env.APP_VERSION || "dev";
const BUILD_TIMESTAMP = process.env.BUILD_TIMESTAMP || "";
const LEGACY_FONT_ERROR_PREFIX = "AutoDraft detected pre-Unicode Indian font text:";

function userFacingErrorMessage(err: unknown, fallback: string): string {
  const message = err instanceof Error ? err.message : String(err || fallback);
  if (message.includes(LEGACY_FONT_ERROR_PREFIX)) {
    return (
      `${message} ` +
      "This is not a retryable AI/backend issue. Convert the Word document from the listed legacy fonts to Unicode first, " +
      "verify Gujarati/Hindi still reads correctly after switching the converted text to Nirmala UI, Noto Sans Gujarati, or Mangal, " +
      "then run Auto Detect again."
    );
  }
  return message || fallback;
}

const useStyles = makeStyles({
  root: {
    minHeight: "100vh",
    padding: "24px",
    backgroundColor: tokens.colorNeutralBackground1,
  },
  versionTag: {
    fontSize: "10px",
    color: tokens.colorNeutralForeground4,
    textAlign: "right" as const,
    marginBottom: "4px",
  },
  title: {
    fontSize: tokens.fontSizeHero800,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    margin: 0,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "24px",
  },
  templateSection: {
    display: "flex",
    flexDirection: "column",
    marginBottom: "32px",
  },
  buttonGroup: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    marginTop: "32px",
    width: "100%",
  },
  buttonContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    width: "100%",
  },
  primaryButton: {
    width: "100%",
    minHeight: "44px",
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    borderRadius: tokens.borderRadiusMedium,
    padding: "12px 24px",
    whiteSpace: "nowrap",
    transition: "all 0.2s ease",
    "&:hover:not(:disabled)": {
      transform: "translateY(-1px)",
      boxShadow: tokens.shadow8,
    },
    "&:active:not(:disabled)": {
      transform: "translateY(0)",
    },
  },
  secondaryButton: {
    width: "100%",
    minHeight: "44px",
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    borderRadius: tokens.borderRadiusMedium,
    padding: "12px 24px",
    whiteSpace: "nowrap",
    borderWidth: "2px" as never,
    transition: "all 0.2s ease",
    "&:hover:not(:disabled)": {
      transform: "translateY(-1px)",
      boxShadow: tokens.shadow4,
      borderColor: tokens.colorBrandForeground1 as never,
    },
    "&:active:not(:disabled)": {
      transform: "translateY(0)",
    },
  },
  variableCount: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorPaletteGreenForeground1,
    fontWeight: tokens.fontWeightSemibold,
    backgroundColor: tokens.colorPaletteGreenBackground1,
    padding: "10px 16px",
    borderRadius: tokens.borderRadiusMedium,
    border: `1px solid ${tokens.colorPaletteGreenBorder1}`,
    marginTop: "4px",
    transition: "all 0.2s ease",
  },
  variableCountIcon: {
    color: tokens.colorPaletteGreenForeground1,
    flexShrink: 0,
  },
  actionLabel: {
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    marginBottom: "8px",
  },
  actionDescription: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightRegular,
    marginBottom: "12px",
    lineHeight: tokens.lineHeightBase300,
  },
  loadingContainer: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "12px 16px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
    marginTop: "8px",
  },
  loadingText: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightRegular,
  },
  errorContainer: {
    marginTop: "8px",
  },
  errorMessage: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorPaletteRedForeground1,
    marginBottom: "8px",
  },
  retryButton: {
    marginTop: "8px",
  },
  accuracyWarning: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorPaletteDarkOrangeForeground1,
    fontWeight: tokens.fontWeightSemibold,
    backgroundColor: tokens.colorPaletteDarkOrangeBackground1,
    padding: "10px 16px",
    borderRadius: tokens.borderRadiusMedium,
    border: `1px solid ${tokens.colorPaletteDarkOrangeBorder1}`,
    marginTop: "4px",
  },
});

type ViewMode = "templateSelector" | "templateCreation" | "formFilling";

/**
 * Re-sorts variables to match the order content controls appear in the document.
 * Falls back to original order if document order cannot be read.
 */
async function sortVariablesByDocumentOrder(variables: any[]): Promise<any[]> {
  try {
    const docOrder = await getContentControlsInDocumentOrder();
    if (docOrder.length === 0) return variables;

    const orderMap = new Map<string, number>();
    docOrder.forEach((tag, idx) => orderMap.set(tag, idx));

    const sorted = [...variables].sort((a, b) => {
      const posA = orderMap.has(a.name) ? orderMap.get(a.name)! : Number.MAX_SAFE_INTEGER;
      const posB = orderMap.has(b.name) ? orderMap.get(b.name)! : Number.MAX_SAFE_INTEGER;
      return posA - posB;
    });

    log(`[App] Re-sorted ${sorted.length} variables to match document order`);
    return sorted;
  } catch (err) {
    log(`[App] Could not sort by document order, using original order: ${err}`);
    return variables;
  }
}

const App: React.FC = () => {
  const styles = useStyles();
  const [viewMode, setViewMode] = useState<ViewMode>("templateCreation");
  const [showDraftingWorkspace, setShowDraftingWorkspace] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [identifiedVariablesCount, setIdentifiedVariablesCount] = useState<number | null>(null);
  const [identificationResponse, setVariableIdentificationResponse] =
    useState<VariableIdentificationResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [previousVariablesCount, setPreviousVariablesCount] = useState<number | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [recentlyUsedTemplates, setRecentlyUsedTemplates] = useState<Template[]>([]);
  const [isLoadingTemplates, setIsLoadingTemplates] = useState<boolean>(false);
  const [templateListError, setTemplateListError] = useState<string | null>(null);
  const [showRenameTemplateDialog, setShowRenameTemplateDialog] = useState(false);
  const [renameTemplateValue, setRenameTemplateValue] = useState("");
  const [showDeleteTemplateDialog, setShowDeleteTemplateDialog] = useState(false);
  const [showCaptureLayoutDialog, setShowCaptureLayoutDialog] = useState(false);
  const [templateActionBusy, setTemplateActionBusy] = useState(false);
  const [captureLayoutBusy, setCaptureLayoutBusy] = useState(false);
  const [hasNavigated, setHasNavigated] = useState<boolean>(false); // Track if user has navigated between screens
  const [isLoadingVariableCount, setIsLoadingVariableCount] = useState<boolean>(false); // Track loading state for variable count fetch
  const [formFillingTemplate, setFormFillingTemplate] = useState<{
    id: string;
    name: string;
    variables: any[];
    initialValues?: Record<string, string>;
  } | null>(null); // Template data for form filling
  // Where to return when the user clicks "Back" from FormFilling. Tracking the
  // source explicitly avoids forcing a re-run of "Auto Detect Variables" when
  // they came from the templateSelector path.
  const [formFillingSource, setFormFillingSource] = useState<ViewMode>("templateCreation");
  // Analysis panel state
  const [showAnalysisPanel, setShowAnalysisPanel] = useState<boolean>(false);
  const [analysisTab, setAnalysisTab] = useState<"summary" | "risk" | "deadlines">("summary");
  const [documentContentForAnalysis, setDocumentContentForAnalysis] = useState<string | null>(null);

  // ── New-template "Auto Draft" STREAMING-creation state ──────────────────
  // App owns the SSE stream for the new-creation path so it survives the
  // templateCreation→formFilling auto-navigation on the first chunk (the form
  // unmounts on nav, which would otherwise orphan the stream's setState calls).
  // These are gated to the new-creation path ONLY — every other flow leaves
  // docReady=true / isStreamingCreation=false so it keeps live-write behavior.
  const [isStreamingCreation, setIsStreamingCreation] = useState<boolean>(false);
  const [streamingVariables, setStreamingVariables] = useState<Variable[]>([]);
  const [docReady, setDocReady] = useState<boolean>(true);
  const [creationDetecting, setCreationDetecting] = useState<boolean>(false);
  const [creationDetectError, setCreationDetectError] = useState<string | null>(null);
  const [streamErrorState, setStreamErrorState] = useState<string | null>(null);
  // Stale-closure-proof accumulator for streamed variables (RAW arrival order).
  const streamFoundRef = useRef<Variable[]>([]);
  // Last FE-cleaned (filter+exact-dedup+disambiguate) view of the accumulator,
  // captured each batch. Reconcile keys off this to retag per-batch-wrapped CCs
  // (FE-disambiguated names) to the backend-authoritative names at complete.
  const lastCleanedRef = useRef<Variable[]>([]);
  // Serializes per-batch Word.run wrap passes so two concurrent chunk_done
  // callbacks never race the same flat-text map / existingTags hash. Each batch
  // chains onto the previous promise so only one Word.run is open at a time.
  // Count of variables wrapped by the last batch that actually ran a wrap pass.
  // A pure-dedup batch (cleaned set did not grow vs this) skips the redundant
  // full-doc text-map rebuild; the list/markers still update via onChunkDone.
  // Last-known set of wrapped CC tags. Lets a pure-dedup batch (which skips the
  // wrap pass) still carry forward each row's link status, so a row that is
  // already located stays green/editable instead of flickering disabled.
  const creationMetaRef = useRef<TemplateMetadata | null>(null);
  const navigatedOnFirstChunkRef = useRef<boolean>(false);
  // Monotonic run token: each Auto Draft streaming session bumps this. Stale
  // stream callbacks / a superseded finalize compare their captured `myRun`
  // against it and bail, so a cancelled or restarted run mutates nothing.
  const runIdRef = useRef(0);
  const streamAbortRef = useRef<AbortController | null>(null);
  // The reusable master OOXML is uploaded in the background so the user can
  // start filling immediately. Complete Drafting waits for this promise before
  // removing controls, guaranteeing that the saved template is durable first.
  const reusableTemplateSavePromiseRef = useRef<Promise<boolean> | null>(null);

  const loadSavedTemplates = async () => {
    setIsLoadingTemplates(true);
    setTemplateListError(null);
    try {
      const response = await listTemplates();
      const loaded = response.templates.map((template) => ({
        id: template.id,
        name: template.name,
      }));
      setTemplates(loaded);
      log(`[App] Loaded ${loaded.length} saved template(s)`);
    } catch (err) {
      const message =
        err instanceof TemplateServiceException
          ? err.message
          : "Could not load saved templates. You can still create a new template from this document.";
      setTemplateListError(message);
      log(`[App] Saved-template list failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsLoadingTemplates(false);
    }
  };

  useEffect(() => {
    let dispose = () => {};
    let active = true;
    (async () => {
      try {
        const reconciliation = await reconcileAutoDraftDocument();
        if (active && reconciliation.status === "needs_repair") {
          setError(`This AutoDraft document needs binding repair: ${reconciliation.issues.map((x) => x.message).join(" ")}`);
        } else if (active && reconciliation.status === "degraded") {
          setError(`Binding integrity is degraded/unverified on this Word host: ${reconciliation.issues.map((x) => x.message).join(" ")}`);
        }
        dispose = await startBindingEventMonitoring((event) => {
          if (!active) return;
          if (event.type === "deleted") {
            setError(`A linked Word field was deleted (${event.bindingId}). Relink fields before relying on this document.`);
          } else {
            log(`[BindingEvent] ${event.bindingId} changed in Word`);
          }
        });
      } catch (eventError) {
        log(`[Reconciliation] non-fatal startup check failed: ${eventError}`);
      }
    })();
    return () => { active = false; dispose(); };
  }, []);

  useEffect(() => {
    // Preload the saved-template catalog so switching the source toggle is
    // instant. A failure is non-blocking for the My document workflow.
    void loadSavedTemplates();
    // Intentionally mount-only: subsequent refreshes happen when the user
    // switches to Saved template or after a new template is created.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDraftSourceChange = (mode: DraftSourceMode) => {
    setSelectedTemplate(null);
    setIdentifiedVariablesCount(null);
    setVariableIdentificationResponse(null);
    setPreviousVariablesCount(null);
    setError(null);

    if (mode === "saved") {
      setViewMode("templateSelector");
      void loadSavedTemplates();
    } else {
      setViewMode("templateCreation");
    }
  };

  const handleRenameSelectedTemplate = async () => {
    if (!selectedTemplate || !renameTemplateValue.trim()) return;
    setTemplateActionBusy(true);
    setError(null);
    try {
      const updated = await updateTemplateMetadata(selectedTemplate.id, { name: renameTemplateValue.trim() });
      const next = { id: updated.id, name: updated.name };
      setTemplates((prev) => prev.map((t) => (t.id === next.id ? next : t)));
      setRecentlyUsedTemplates((prev) => prev.map((t) => (t.id === next.id ? next : t)));
      setSelectedTemplate(next);
      setShowRenameTemplateDialog(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not rename template.");
    } finally {
      setTemplateActionBusy(false);
    }
  };

  const handleDeleteSelectedTemplate = async () => {
    if (!selectedTemplate) return;
    setTemplateActionBusy(true);
    setError(null);
    try {
      const id = selectedTemplate.id;
      await deleteTemplate(id);
      setTemplates((prev) => prev.filter((t) => t.id !== id));
      setRecentlyUsedTemplates((prev) => prev.filter((t) => t.id !== id));
      setSelectedTemplate(null);
      setPreviousVariablesCount(null);
      setShowDeleteTemplateDialog(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete template.");
    } finally {
      setTemplateActionBusy(false);
    }
  };

  const handleDuplicateSelectedTemplate = async () => {
    if (!selectedTemplate) return;
    setTemplateActionBusy(true); setError(null);
    try {
      const duplicated = await duplicateTemplate(selectedTemplate.id);
      const next = { id: duplicated.id, name: duplicated.name };
      setTemplates((prev) => [next, ...prev]);
      setRecentlyUsedTemplates((prev) => [next, ...prev.filter((t) => t.id !== next.id)].slice(0,5));
      setSelectedTemplate(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not duplicate template."); }
    finally { setTemplateActionBusy(false); }
  };

  const handleTemplateSelect = (template: Template | null) => {
    log("📋 FRONTEND: Template selected:", template ? template.name : "None");
    setSelectedTemplate(template);
    // Reset identified variables when template changes
    setIdentifiedVariablesCount(null);
    setVariableIdentificationResponse(null);
    setError(null);
    setIsLoading(false);

    // Note: Variable count is now loaded in handleTemplateSelectWithVariables
    // This function just handles the basic selection state
    if (template) {
      log(
        `✅ FRONTEND: Template "${template.name}" selected - "Auto Detect Variables" button should now be enabled`
      );
      setRecentlyUsedTemplates((prev) => {
        const filtered = prev.filter((t) => t.id !== template.id);
        return [template, ...filtered].slice(0, 5);
      });
    } else {
      setPreviousVariablesCount(null);
      warn('⚠️ FRONTEND: Template deselected - "Auto Detect Variables" button will be disabled');
    }
  };

  const handleIdentifyVariables = async () => {
    log('🔘 FRONTEND: "Identify Variables" button clicked');
    log(`  Template selected: ${Boolean(selectedTemplate)}`);

    if (!selectedTemplate) {
      warn("⚠️ FRONTEND: No template selected - cannot proceed");
      return;
    }

    // Reset previous state
    setError(null);
    setVariableIdentificationResponse(null);
    setIsLoading(true);

    log("═══════════════════════════════════════════════════════════");
    log("🚀 FRONTEND: Starting variable identification process");
    log("═══════════════════════════════════════════════════════════");
    log("[App] Template selected for variable identification");
    log(`API Target: ${window.location.hostname === "localhost" ? "LOCALHOST (dev proxy)" : "PROD: https://word-addin.duckdns.org"}`);

    try {
      // Step 1: Extract document content using Office.js
      info("📄 Step 1: Extracting document content from Word...");

      // Check if running in Office context
      if (typeof Word === "undefined") {
        throw new Error(
          "Word API is not available. This add-in must be run within Microsoft Word. " +
            "Please load the add-in in Word, not in a browser directly."
        );
      }

      const documentContent = await extractDocumentContent();
      log(`✅ Document content extracted: ${documentContent.length} characters`);

      // Store document content for analysis features
      if (documentContent.text) {
        setDocumentContentForAnalysis(documentContent.text);
      }

      if (!documentContent.text || documentContent.text.trim().length === 0) {
        throw new Error(
          "Document is empty. Please add content to your document before identifying variables."
        );
      }

      // Pre-Unicode Gujarati/Hindi fonts store glyph codes rather than the text
      // Word visually displays. In Word taskpane mode, lawyers still need the
      // original combined document preserved, so continue in guarded legacy-font
      // mode and require human review of detected fields.
      await assertDocumentTextIsUnicodeSafe({ allowLegacyFonts: true });

      // Step 2: Inspect red/blue formatting as a diagnostic/fallback signal only.
      // In the real corpus these colours are also used for fixed headings, labels,
      // advocate details and emphasis, so colour is NOT authoritative variable truth.
      info("🎨 Step 2: Inspecting colored text candidates (fallback only)...");
      const colorVars = await extractColoredTextVariables();
      log(`✅ Step 2: Found ${colorVars.length} colored formatting candidates (not auto-accepted)`);

      // Step 3: Call AI variable identification API (always attempt, graceful on failure)
      let response: VariableIdentificationResponse;
      let aiExtras: Variable[] = [];
      let aiSucceeded = false;
      try {
        info("🔗 Step 3: Calling AI variable identification API...");
        log(`  Connecting to backend...`);
        // Load existing variables for this template to use as AI hints
        let knownVars: Variable[] | undefined;
        try {
          const existing = await getTemplate(selectedTemplate.id);
          if (existing.variables && existing.variables.length > 0) {
            knownVars = existing.variables;
            log(`  Including ${knownVars.length} existing variables as hints for AI`);
          }
        } catch {
          log(`  Could not load existing variables for hints (template may be new)`);
        }
        const aiResponse = await identifyVariables(
          documentContent.text,
          selectedTemplate.id,
          selectedTemplate.name,
          knownVars
        );
        log(`✅ Step 3: API call completed successfully`);

        // The backend result already unions deterministic legal-field extractors
        // with the LLM. Do NOT union raw red/blue runs here: in these documents
        // colour is presentation, not a reliable variable annotation.
        aiExtras = aiResponse.variables;
        response = aiResponse;
        aiSucceeded = true;
      } catch (aiError) {
        // Reliability invariant: AI/semantic detection failure is not equivalent
        // to successful field detection. Never mutate Word from color-only or
        // deterministic emergency fallbacks after a failed semantic run.
        throw aiError;
      }

      // Step 4: Use semantic backend variables. Coloured runs are only a
      // last-resort fallback if the backend call itself failed.
      info("📊 Step 4: Selecting authoritative variables...");
      // Drop numbered list markers / footnote refs (e.g. "[1]", "(2)") and
      // collapse duplicates that share the SAME originalText under different
      // semantic names (the AI occasionally returns the same span as both
      // "Accused Proprietor Name" and "Accused Authorized Person", which would
      // otherwise produce duplicate form fields bound to the same control).
      //
      // Substring-overlap dedup is intentionally NOT applied here so that a
      // wider label-anchored span (e.g. "Cheque No.: 123456") and a bare span
      // sitting inside it ("123456") both survive. Backend mirrors this in
      // OllamaService::merge_extractor_and_llm.
      const mergedVariables = aiSucceeded ? aiExtras : colorVars;
      log(
        aiSucceeded
          ? `✅ Step 4: Using ${mergedVariables.length} semantic backend variables; ignored ${colorVars.length} raw colour-only candidates`
          : `⚠️ Step 4: Backend unavailable; using ${mergedVariables.length} colour candidates as emergency fallback`
      );

      // Update response with merged variables
      response.variables = mergedVariables;

      setVariableIdentificationResponse(response);
      setIdentifiedVariablesCount(response.variables.length);

      // Step 5: Wrap variables in the Word document via structural binding plan
      if (response.variables && response.variables.length > 0) {
        try {
          info("🔄 Step 5: Wrapping variables in document...");
          log(`  Wrapping ${response.variables.length} variables via binding plan...`);
          const wrapStats5 = await wrapVariablesWithBindingPlan(response.variables);
          log(
            `✅ Step 5: Wrap stats: ${wrapStats5.wrapped}/${wrapStats5.total} wrapped, ` +
              `${wrapStats5.missedFlat} missedFlat, ${wrapStats5.errors} errors`
          );
        } catch (replaceError) {
          logError("[App] Variable wrapping failed", replaceError);
          warn(`⚠️ Warning: Failed to wrap variables in document: ${replaceError}`);
          // Continue - user can still proceed
        }
      }

      // User-facing quality is represented by actual Word linkage/review state,
      // not a model confidence percentage. Backend messages still surface when
      // deterministic coverage or the AI service needs attention.
      if (response.message) {
        warn(`⚠️ Backend message: ${response.message}`);
        setError(response.message);
      }

      log("═══════════════════════════════════════════════════════════");
      log("✅ FRONTEND: Variable identification process completed");
      log("═══════════════════════════════════════════════════════════");
      log("Final Results:", {
        count: response.variables.length,
        accuracy: response.identificationPercentage,
        status: response.status,
      });
      log("═══════════════════════════════════════════════════════════");
    } catch (err) {
      logError("[App] Variable identification failed", err);

      // Handle specific error types
      if (err instanceof AiTimeoutException) {
        setError("Request timed out. The AI service took too long to respond. Please try again.");
      } else if (err instanceof AiRetryExhaustedException) {
        setError("Unable to connect to AI service after multiple attempts. Please check your connection and try again.");
      } else if (err instanceof AiServiceException) {
        setError(err.message || "An error occurred while identifying variables. Please try again.");
      } else if (err instanceof Error) {
        const errorMsg = userFacingErrorMessage(err, "An unexpected error occurred.");
        if (errorMsg.includes("fetch") || errorMsg.includes("Failed to fetch") || errorMsg.includes("Network")) {
          setError(`Network error: ${errorMsg}. Please ensure the backend server is running and accessible.`);
        } else if (errorMsg.includes(LEGACY_FONT_ERROR_PREFIX)) {
          setError(errorMsg);
        } else {
          setError(`${errorMsg} Please try again or use manual variable identification.`);
        }
      } else {
        setError("An unknown error occurred. Please try again or use manual variable identification.");
      }

      // Reset count on error
      setIdentifiedVariablesCount(null);
      setVariableIdentificationResponse(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRetry = () => {
    handleIdentifyVariables();
  };

  // ──────────────────────────────────────────────────────────────────────
  // New-template "Auto Draft" streaming-creation orchestration. App owns the
  // SSE stream because the templateCreation→formFilling auto-navigation on the
  // first chunk unmounts TemplateCreationForm — keeping the stream in App lets
  // onChunkDone/onComplete keep mutating state after we navigate.
  //
  // PRODUCT DECISION (batch-by-batch application): as each chunk_done batch
  // arrives we clean the ACCUMULATED set (filter list-markers + exact dedup +
  // cross-batch name disambiguation — the same cleanup the backend defers to
  // 'complete') and wrap the whole cleaned set, so content-controls appear
  // progressively and the user can fill them live. wrapVariablesWithBindingPlan
  // short-circuits already-wrapped tags via getByTag, so re-passing the growing
  // set each batch is mostly no-ops and gives late-arriving label-anchored
  // PARENT spans a retry after the deterministic child anchor wrapped first.
  // RESIDUAL RISK (accepted): once a child CC exists a later parent may nest or
  // be partially blocked — longest-wins is only enforced WITHIN one wrap call.
  //
  // HARD RULES (see CLAUDE.md): persistence ALWAYS uses the backend-authoritative
  // 'complete' list (never the per-chunk accumulator). At complete we reconcile
  // FE-disambiguated CC tags to the authoritative names (renameContentControlTag)
  // so typed values reach the right control.
  // ──────────────────────────────────────────────────────────────────────

  const navigateToStreamingForm = (metadata: TemplateMetadata, vars: Variable[]) => {
    // id:"" deliberately keeps the debounced DB-save effect dormant (its
    // `if (!templateId)` guard short-circuits) until finalize sets the real id.
    setFormFillingTemplate({ id: "", name: metadata.name, variables: vars });
    setFormFillingSource("templateCreation");
    setIsStreamingCreation(true);
    setViewMode("formFilling");
    setHasNavigated(true);
    setCreationDetecting(false);
  };

  const handleStreamingError = (err: unknown) => {
    const message = userFacingErrorMessage(err, "Variable identification failed.");
    log(`[App] Streaming creation error: ${message}`);
    if (!navigatedOnFirstChunkRef.current) {
      // Pre-navigation failure: stay on the Auto Draft screen and surface it.
      setCreationDetecting(false);
      setCreationDetectError(message);
      setIsStreamingCreation(false);
      setDocReady(true);
    } else {
      // Post-navigation failure: stay on the form, show a stream-error banner,
      // and leave docReady=false so Complete Drafting stays gated. KEEP the full
      // accumulated list visible — promote the latest streamed accumulator into
      // formFillingTemplate.variables BEFORE flipping isStreamingCreation off, so
      // the render does not fall back to the (smaller) first-chunk snapshot and
      // drop later rows + their buffered values.
      const latest = [...streamFoundRef.current];
      setFormFillingTemplate((prev) => (prev ? { ...prev, variables: latest } : prev));
      setStreamErrorState(message);
      setIsStreamingCreation(false);
    }
  };

  const handleCreateError = (err: unknown) => {
    let message: string;
    if (err instanceof TemplateServiceException && err.statusCode === 409) {
      message = `A template named "${creationMetaRef.current?.name ?? ""}" already exists — go Back and rename.`;
    } else if (err instanceof Error) {
      message = err.message || "Failed to save template.";
    } else {
      message = "Failed to save template. Please try again.";
    }
    log(`[App] Streaming creation persist error: ${message}`);
    if (!navigatedOnFirstChunkRef.current) {
      setCreationDetecting(false);
      setCreationDetectError(message);
    } else {
      // Post-navigation persist failure: keep the full accumulated list visible
      // (same list-shrink guard as handleStreamingError) so a create error after
      // navigation does not revert the form to the first-chunk snapshot.
      const latest = [...streamFoundRef.current];
      setFormFillingTemplate((prev) => (prev ? { ...prev, variables: latest } : prev));
      setStreamErrorState(message);
    }
    setIsStreamingCreation(false);
    // Do NOT flip docReady true — Complete Drafting stays gated on a half-built
    // (wrapped-but-not-persisted) draft.
  };

  const finalizeStreamingCreation = async (
    resp: VariableIdentificationResponse,
    metadata: TemplateMetadata,
    myRun: number
  ) => {
    if (resp.status === "unavailable" || resp.status === "failed") {
      setCreationDetecting(false);
      setIsStreamingCreation(false);
      setDocReady(true);
      setCreationDetectError(resp.message || "Field detection could not be completed. The Word document was not modified.");
      return;
    }
    const authoritative: Variable[] = resp.variables || [];
    if (resp.status === "no_fields" || authoritative.length === 0) {
      setCreationDetecting(false);
      setIsStreamingCreation(false);
      setDocReady(true);
      setCreationDetectError(resp.message || "No reusable fields were found. The Word document was not modified.");
      return;
    }
    if (myRun !== runIdRef.current) return;

    try {
      const wrapStats = await wrapVariablesWithBindingPlan(authoritative);
      log(
        `[App] Streaming finalize wrap: ${wrapStats.wrapped}/${wrapStats.total} wrapped, ` +
          `${wrapStats.missedFlat} missedFlat, ${wrapStats.errors} errors`
      );
    } catch (e) {
      warn(`[App] Streaming finalize wrap failed: ${e}`);
    }
    if (myRun !== runIdRef.current) return;

    const tags = new Set(await getContentControlsInDocumentOrder());
    if (myRun !== runIdRef.current) return;
    const annotated = authoritative.map((variable) => ({
      ...variable,
      // Extraction already supplies a stable UUID binding ID. Keep a UUID-like
      // local id so rename/edit works before any PostgreSQL row exists.
      id: variable.id || variable.bindingId || crypto.randomUUID(),
      hasContentControl: tags.has(variable.bindingId || variable.name),
    }));
    const sorted = await sortVariablesByDocumentOrder(annotated);
    if (myRun !== runIdRef.current) return;

    // Persistence boundary: a fresh Auto Draft remains entirely local until the
    // user explicitly chooses to save a reusable template. Back/cancel can
    // therefore never leave a ghost row in Saved Templates.
    creationMetaRef.current = metadata;
    navigatedOnFirstChunkRef.current = true;
    navigateToStreamingForm(metadata, sorted);
    setFormFillingTemplate({ id: "", name: metadata.name, variables: sorted });
    setSelectedTemplate(null);
    setIsStreamingCreation(false);
    setCreationDetecting(false);
    setDocReady(true);
    streamAbortRef.current = null;
    try {
      await syncAutoDraftBindingManifest(sorted, {});
    } catch (e) {
      log(`[App] Unsaved draft manifest sync skipped: ${e instanceof Error ? e.message : e}`);
    }
  };

  const handleAutoDetectStreaming = async (metadata: TemplateMetadata) => {
    if (typeof Word === "undefined") {
      setCreationDetectError(
        "Word API is not available. This add-in must be run within Microsoft Word."
      );
      return;
    }

    // Reset the streaming session and claim a fresh run token. Any prior
    // in-flight stream/finalize is now superseded (its captured myRun won't
    // match runIdRef.current) and will bail on its next callback.
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    const myRun = ++runIdRef.current;
    navigatedOnFirstChunkRef.current = false;
    streamFoundRef.current = [];
    lastCleanedRef.current = [];
    creationMetaRef.current = metadata;
    setStreamingVariables([]);
    setStreamErrorState(null);
    setCreationDetectError(null);
    setCreationDetecting(true);
    setDocReady(false);
    setIsStreamingCreation(true);
    reusableTemplateSavePromiseRef.current = null;

    try {
      const documentContent = await extractDocumentContent();
      if (!documentContent.text || documentContent.text.trim().length === 0) {
        throw new Error(
          "Document is empty. Please add content to your document before detecting variables."
        );
      }

      await assertDocumentTextIsUnicodeSafe({ allowLegacyFonts: true });

      // Store document content for analysis features
      setDocumentContentForAnalysis(documentContent.text);

      if (supportsResponseStreaming()) {
        log("[App] Auto Draft streaming creation: using SSE streaming");
        identifyVariablesStreaming(
          documentContent.text,
          {
            onChunkDone: (_idx, _total, vars) => {
              if (myRun !== runIdRef.current) return;
              // Transactional detection: chunk results are progress-only. Do not
              // mutate Word or navigate into editable field state until the
              // authoritative complete event has been validated.
              streamFoundRef.current.push(...vars);
              const cleaned = cleanAccumulated<Variable>(streamFoundRef.current);
              lastCleanedRef.current = cleaned;
              setStreamingVariables(cleaned.map((v) => ({ ...v, hasContentControl: false })));
            },
            onProgress: (_completed, _total) => {
              // no-op: we navigate on the first chunk, before progress matters
              if (myRun !== runIdRef.current) return;
            },
            onChunkError: (idx, msg) => {
              if (myRun !== runIdRef.current) return;
              log(`[App] Streaming chunk ${idx + 1} error: ${msg}`);
            },
            onComplete: (resp) => {
              if (myRun !== runIdRef.current) return;
              finalizeStreamingCreation(resp, metadata, myRun);
            },
            onError: (err) => {
              if (myRun !== runIdRef.current) return;
              handleStreamingError(err);
            },
          },
          undefined,
          metadata.name,
          undefined,
          controller.signal
        );
      } else {
        log("[App] Auto Draft streaming creation: streaming unsupported — batch fallback");
        const resp = await identifyVariablesViaJob(
          documentContent.text,
          undefined,
          metadata.name,
          undefined,
          controller.signal
        );
        if (myRun !== runIdRef.current) return;
        const vars = resp.variables || [];
        streamFoundRef.current = [...vars];
        setStreamingVariables([...vars]);
        // Only navigate when the batch actually found variables; a zero-variable
        // batch leaves navigatedOnFirstChunkRef false so finalize's FIX 1 guard
        // surfaces the "no variables" message instead of persisting an empty one.
        if (vars.length > 0) {
          navigatedOnFirstChunkRef.current = true;
          navigateToStreamingForm(metadata, vars);
        }
        await finalizeStreamingCreation(resp, metadata, myRun);
      }
    } catch (err) {
      if (myRun !== runIdRef.current) return;
      handleStreamingError(err);
    }
  };

  const handleCaptureCurrentDocumentAsTemplateLayout = async () => {
    if (!selectedTemplate) return;
    setCaptureLayoutBusy(true);
    setError(null);
    try {
      const template = await getTemplate(selectedTemplate.id);
      if (template.variables.length > 0) {
        await wrapVariablesWithBindingPlan(template.variables);
      }
      const tags = new Set(await getContentControlsInDocumentOrder());
      const annotated = template.variables.map((v: any) => ({
        ...v,
        hasContentControl: tags.has(v.bindingId || v.name),
      }));
      const ooxml = await getReusableTemplateBodyOoxml(annotated);
      if (!ooxml || !ooxml.trim()) {
        throw new Error("Word did not return a reusable document layout.");
      }
      await updateTemplateContent(selectedTemplate.id, ooxml);
      try {
        await syncAutoDraftBindingManifest(annotated, { templateId: selectedTemplate.id });
      } catch (e) {
        log(`[App] Manifest sync after layout recovery skipped: ${e instanceof Error ? e.message : e}`);
      }
      setShowCaptureLayoutDialog(false);
      setError("Reusable layout captured. You can now open this saved template.");
    } catch (e) {
      setError(`Could not capture the current document as the reusable layout: ${e instanceof Error ? e.message : e}`);
    } finally {
      setCaptureLayoutBusy(false);
    }
  };

  const handleUseTemplate = async () => {
    if (!selectedTemplate) {
      warn("⚠️ FRONTEND: No template selected - cannot use template");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Capture document content for analysis
      try {
        const doc = await extractDocumentContent();
        if (doc.text) setDocumentContentForAnalysis(doc.text);
      } catch { /* ignore - analysis is optional */ }

      log("[App] Applying selected template");
      // Fetch content (OOXML) and template (metadata+variables) in parallel
      const [contentRes, templateRes] = await Promise.all([
        getTemplateContent(selectedTemplate.id),
        getTemplate(selectedTemplate.id),
      ]);

      if (!contentRes.bodyOoxml || contentRes.bodyOoxml.trim().length === 0) {
        setError(null);
        setShowCaptureLayoutDialog(true);
        return;
      }

      info("[App] Inserting template body into document...");
      await insertOoxmlIntoDocument(contentRes.bodyOoxml);
      log(
        `[App] Inserted template body, opening form with ${templateRes.variables.length} variables`
      );

      // Wrap variables in Content Controls with highlighting
      const wrapStatsUse = await wrapVariablesWithBindingPlan(templateRes.variables);
      log(
        `[App] Wrap stats: ${wrapStatsUse.wrapped}/${wrapStatsUse.total} wrapped, ` +
          `${wrapStatsUse.missedFlat} missedFlat, ${wrapStatsUse.errors} errors`
      );

      // Annotate which variables actually got a CC after wrapping (some may
      // be ghosts — substring overlaps or text the AI invented). The form
      // uses this to badge bound vs. unbound rows.
      const useDocTags = new Set(await getContentControlsInDocumentOrder());
      const annotatedVars = templateRes.variables.map((v: any) => ({
        ...v,
        hasContentControl: useDocTags.has(v.bindingId || v.name),
      }));
      try {
        await syncAutoDraftBindingManifest(annotatedVars, { templateId: templateRes.id });
      } catch (e) {
        log(`[App] Document manifest sync skipped: ${e instanceof Error ? e.message : e}`);
      }

      const sortedVars = await sortVariablesByDocumentOrder(annotatedVars);
      setFormFillingTemplate({
        id: templateRes.id,
        name: templateRes.name,
        variables: sortedVars,
      });
      // Defensive: this flow always renders in live-write mode (Constraint D).
      setDocReady(true);
      setIsStreamingCreation(false);
      setFormFillingSource("templateSelector");
      setViewMode("formFilling");
      setHasNavigated(true);
    } catch (err) {
      logError("[App] Template application failed", err);
      setError(
        err instanceof TemplateServiceException
          ? err.message
          : `Failed to use template: ${err instanceof Error ? err.message : "Unknown error"}. Please try again.`
      );
      log(`[App] Error using template: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFillForm = async () => {
    if (!selectedTemplate) {
      warn("⚠️ FRONTEND: No template selected - cannot fill form");
      return;
    }

    // Load template with variables from database
    setIsLoading(true);
    setError(null);

    try {
      // Capture document content for analysis
      try {
        const doc = await extractDocumentContent();
        if (doc.text) setDocumentContentForAnalysis(doc.text);
      } catch { /* ignore - analysis is optional */ }

      log(
        `[App] Loading template ${selectedTemplate.id} with variables from database for form filling...`
      );
      const loadedTemplate = await getTemplate(selectedTemplate.id);

      log(
        `[App] Loaded template "${selectedTemplate.name}" with ${loadedTemplate.variables.length} variables`
      );

      // Before wrapping, read any existing content control values.
      // If content controls already exist (active draft), wrapVariablesWithBindingPlan
      // short-circuits via getByTag and leaves them untouched.
      // If they don't exist (after Complete Draft), we need to check what text
      // is actually in the document — it may differ from the DB's originalText.
      const existingValues = await readAllContentControlValues();
      const hasExistingControls = Object.keys(existingValues).length > 0;
      log(
        `[App] Existing content controls: ${hasExistingControls ? Object.keys(existingValues).length + " found" : "none"}`
      );
      if (hasExistingControls) {
        log(`[App] Existing content-control values present (${Object.keys(existingValues).length})`);
      }

      // Build variables with current document text as originalText.
      // This ensures wrapVariablesWithBindingPlan can find the actual text in the document
      // after a previous draft was completed (document has filled values, not master template text).
      // Priority: existing content control values > DB currentValue > last known form values > DB originalText
      const variablesForDocument = loadedTemplate.variables.map((v: any) => {
        // 1. If controls exist with a value for this variable, use that
        const existingVal = existingValues[v.name];
        if (existingVal && existingVal.trim() && existingVal.trim() !== v.name) {
          return { ...v, originalText: existingVal.trim() };
        }
        // 2. If DB has a persisted currentValue (survives page reload), use that
        if (v.currentValue && v.currentValue.trim() && v.currentValue.trim() !== v.name) {
          return { ...v, originalText: v.currentValue.trim() };
        }
        // 3. If we have last known values from a previous form session, use those
        const lastVal = lastKnownValues[v.name];
        if (lastVal && lastVal.trim() && lastVal.trim() !== v.name) {
          return { ...v, originalText: lastVal.trim() };
        }
        // 4. Fall back to DB originalText
        return v;
      });

      // Wrap variables in Content Controls with highlighting
      const wrapStats = await wrapVariablesWithBindingPlan(variablesForDocument);
      log(
        `[App] Wrap stats: ${wrapStats.wrapped}/${wrapStats.total} wrapped, ` +
          `${wrapStats.missedFlat} missedFlat, ${wrapStats.missedRange} missedRange, ` +
          `${wrapStats.skippedAlreadyWrapped} skipped, ${wrapStats.errors} errors`
      );

      // Read current values from content controls immediately so the form
      // shows filled values right away (e.g. when resuming a draft)
      const currentValues = await readAllContentControlValues();

      // Filter out "unfilled placeholder" values where text == variable name
      // e.g. content control text "{Advocate Name}" with tag "Advocate Name" → value "Advocate Name" == tag → unfilled
      // Also merge in DB-persisted currentValue for any variables that don't have a content control value
      const filteredValues: Record<string, string> = {};
      for (const v of loadedTemplate.variables) {
        const ccVal = currentValues[v.name];
        if (ccVal && ccVal.trim() && ccVal.trim() !== v.name) {
          filteredValues[v.name] = ccVal;
        } else if (v.currentValue && v.currentValue.trim() && v.currentValue.trim() !== v.name) {
          filteredValues[v.name] = v.currentValue;
        }
      }

      const filledCount = Object.values(filteredValues).filter((v) => v && v.trim()).length;
      log(`[App] Read ${filledCount} pre-filled values from document`);
      log(`[App] Form values prepared (${Object.keys(filteredValues).length})`);

      // Annotate which variables are bound to a content control in the
      // current doc state so the form can badge bound vs. unbound rows.
      const fillFormDocTags = new Set(await getContentControlsInDocumentOrder());
      const annotatedFillVars = loadedTemplate.variables.map((v: any) => ({
        ...v,
        hasContentControl: fillFormDocTags.has(v.bindingId || v.name),
      }));
      const boundCount = annotatedFillVars.filter((v: any) => v.hasContentControl).length;
      log(
        `[App] Form variables: ${boundCount}/${annotatedFillVars.length} bound to content controls`
      );
      const unboundNames = annotatedFillVars
        .filter((v: any) => !v.hasContentControl)
        .map((v: any) => v.name);
      if (unboundNames.length > 0) {
        log(`[App] Unbound variable count: ${unboundNames.length}`);
      }

      // Store template data for form filling, sorted by document order
      const sortedVars = await sortVariablesByDocumentOrder(annotatedFillVars);
      setFormFillingTemplate({
        id: loadedTemplate.id,
        name: loadedTemplate.name,
        variables: sortedVars,
        initialValues: filteredValues,
      });

      // Switch to form filling view
      // Defensive: this flow always renders in live-write mode (Constraint D).
      setDocReady(true);
      setIsStreamingCreation(false);
      setFormFillingSource("templateSelector");
      setViewMode("formFilling");
      setHasNavigated(true);
    } catch (error) {
      logError("[App] Template load failed", error);
      setError(
        error instanceof TemplateServiceException
          ? error.message
          : "Failed to load template from database. Please try again."
      );
      log(
        `[App] Error loading template: ${error instanceof Error ? error.message : "Unknown error"}`
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleRenameVariable = async (
    variableId: string,
    oldName: string,
    newName: string
  ): Promise<Variable> => {
    if (!formFillingTemplate) {
      throw new Error("No active template is available for renaming.");
    }

    const currentVar = formFillingTemplate.variables.find((v) => v.id === variableId);
    if (!currentVar) throw new Error("Variable was not found in the active draft.");

    if (!currentVar.bindingId) await renameContentControlTag(oldName, newName);
    else await setContentControlTitleByTag(currentVar.bindingId, newName);

    let updated: Variable;
    if (!formFillingTemplate.id) {
      // Fresh AutoDraft: no database row exists yet. Rename only the Word field
      // and local draft state; persistence occurs at explicit completion.
      updated = { ...currentVar, name: newName };
    } else {
      try {
        updated = await updateVariable(variableId, newName);
      } catch (error) {
        try {
          if (!currentVar.bindingId) await renameContentControlTag(newName, oldName);
          else await setContentControlTitleByTag(currentVar.bindingId, oldName);
        } catch (rollbackError) {
          logError("[App] Word tag rollback failed", rollbackError);
        }
        throw error;
      }
    }

    const nextVariables = formFillingTemplate.variables.map((variable) =>
      variable.id === variableId
        ? { ...variable, ...updated, hasContentControl: variable.hasContentControl }
        : variable
    );
    setFormFillingTemplate((prev) => prev ? { ...prev, variables: nextVariables } : prev);
    setStreamingVariables((prev) =>
      prev.map((variable) =>
        variable.id === variableId
          ? { ...variable, ...updated, hasContentControl: variable.hasContentControl }
          : variable
      )
    );
    setLastKnownValues((prev) => {
      if (!(oldName in prev)) return prev;
      const next = { ...prev, [updated.name]: prev[oldName] };
      delete next[oldName];
      return next;
    });

    if (formFillingTemplate.id) {
      try {
        const cleanOoxml = await getReusableTemplateBodyOoxml(nextVariables);
        if (cleanOoxml) {
          reusableTemplateSavePromiseRef.current = updateTemplateContent(
            formFillingTemplate.id,
            cleanOoxml
          ).then(() => true).catch((error) => {
            logError("[App] Reusable template refresh after rename failed", error);
            return false;
          });
        }
      } catch (error) {
        reusableTemplateSavePromiseRef.current = Promise.resolve(false);
        logError("[App] Reusable template capture after rename failed", error);
      }
    }

    return updated;
  };

  const handleApplyVariableValues = async (
    variableName: string,
    newValue: string,
    originalText?: string,
    bindingId?: string
  ) => {
    try {
      log("[App] Updating document variable");
      await updateVariableInDocument(variableName, newValue, originalText, bindingId);
      log("[App] Document variable updated");
    } catch (error) {
      logError("[App] Document variable update failed", error);
      throw new Error(
        `Failed to update variable "${variableName}": ${error instanceof Error ? error.message : "Unknown error"}`
      );
    }
  };

  const handleVerifyDraft = async (): Promise<VerificationReport> => {
    if (!formFillingTemplate) throw new Error("No active draft is available to verify.");
    const finalDocument = await extractDocumentContent();
    const liveValues = await readAllContentControlValues();
    return verifyFinalDocument(finalDocument.text, formFillingTemplate.variables, liveValues, identificationResponse?.identificationMode !== "general");
  };

  const handleSaveCurrentDraftAsTemplate = async () => {
    if (!formFillingTemplate) throw new Error("No active draft is available.");
    if (formFillingTemplate.id) return;
    const metadata = creationMetaRef.current || {
      name: formFillingTemplate.name, type: "", subtype: "", description: "",
    };
    const variables = formFillingTemplate.variables;
    const cleanOoxml = await getReusableTemplateBodyOoxml(variables);
    if (!cleanOoxml?.trim()) throw new Error("Could not capture the reusable empty template layout.");
    let createdId: string | null = null;
    try {
      const created = await createTemplate(
        metadata,
        variables.map((variable) => ({ ...variable, id: undefined, currentValue: undefined }))
      );
      createdId = created.id;
      await updateTemplateContent(created.id, cleanOoxml);
      await clearVariableValues(created.id, variables.map((variable) => variable.name));
      try { await syncAutoDraftBindingManifest(variables, { templateId: created.id }); } catch {}
      const saved = { id: created.id, name: created.name || metadata.name };
      setTemplates((prev) => [saved, ...prev.filter((item) => item.id !== saved.id)]);
      setRecentlyUsedTemplates((prev) => [saved, ...prev.filter((item) => item.id !== saved.id)].slice(0, 5));
      setSelectedTemplate(saved);
      setFormFillingTemplate((prev) => prev ? { ...prev, id: created.id } : prev);
      log(`[App] Explicitly saved reusable template ${created.id}`);
    } catch (error) {
      if (createdId) { try { await deleteTemplate(createdId); } catch {} }
      throw error;
    }
  };

  const handleCompleteDrafting = async () => {
    if (!formFillingTemplate) throw new Error("No active draft is available.");
    try {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      await valueSavePromiseRef.current;
      if (formFillingTemplate.id) {
        await clearVariableValues(
          formFillingTemplate.id,
          formFillingTemplate.variables.map((variable) => variable.name)
        );
      }
      setLastKnownValues({});
      log("[App] Current document completed without forcing reusable-template creation.");
    } catch (err) {
      logError("[App] Complete drafting failed", err);
      throw new Error(`Failed to complete drafting: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  };

  const handleDraftFinalized = () => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    // After Complete Drafting, the user explicitly wants to land back on the
    // first screen. Clear all derived state so they get a clean slate; if they
    // want to edit again they re-enter via "Fill the form".
    log("[App] Draft finalized — returning to first screen");
    setFormFillingTemplate(null);
    setSelectedTemplate(null);
    setIdentifiedVariablesCount(null);
    setVariableIdentificationResponse(null);
    setLastKnownValues({});
    setError(null);
    setHasNavigated(false);
    // Clean slate for the streaming-creation session.
    setIsStreamingCreation(false);
    setStreamingVariables([]);
    setDocReady(true);
    setCreationDetectError(null);
    setStreamErrorState(null);
    reusableTemplateSavePromiseRef.current = null;
    void loadSavedTemplates();
    setViewMode("templateCreation");
  };

  // Store the last known form values so we can use them when resuming via "Fill the form"
  const [lastKnownValues, setLastKnownValues] = useState<Record<string, string>>({});
  const saveTimerRef = useRef<number | null>(null);
  const valueSavePromiseRef = useRef<Promise<void>>(Promise.resolve());

  // Debounced save of variable values to database whenever form values change
  useEffect(() => {
    const templateId = formFillingTemplate?.id;
    if (!templateId || Object.keys(lastKnownValues).length === 0) {
      return () => {
        /* noop */
      };
    }

    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
    }

    saveTimerRef.current = window.setTimeout(async () => {
      const savePromise = saveVariableValues(templateId, lastKnownValues)
        .then(() => undefined)
        .catch((err) => {
          logError("[App] Variable persistence failed", err);
        });
      valueSavePromiseRef.current = savePromise;
      await savePromise;
    }, 2000) as unknown as number;

    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, [lastKnownValues, formFillingTemplate?.id]);

  const handleBackFromFormFilling = () => {
    // Back during an in-flight streaming creation cancels it: invalidate the
    // active run so late onChunkDone/onComplete/onError callbacks AND a
    // multi-second finalize bail on their `myRun !== runIdRef.current` guards,
    // so no partial template is created and no further state is mutated. (The
    // AbortController closes the transport; the run token also suppresses late callbacks.)
    if (isStreamingCreation) {
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      runIdRef.current += 1;
      setIsStreamingCreation(false);
      setStreamingVariables([]);
      setDocReady(true);
      setStreamErrorState(null);
    }
    // Preserve selectedTemplate, identificationResponse, and formFillingTemplate
    // so the user can return to the form without re-running "Auto Detect" or
    // re-fetching the template. Route to wherever they came from.
    setViewMode(formFillingSource);
    setError(null);
  };

  const handleTemplateFormSubmit = async (metadata: TemplateMetadata, templateId?: string) => {
    log("Template form submitted:", metadata);

    if (!templateId) {
      warn("⚠️ Template ID not provided, cannot navigate to form filling");
      setViewMode("templateSelector");
      return;
    }

    // Fast path: when the user is returning to a form they were just on
    // (Back → "Fill the form" again), the in-memory state is still valid.
    // Skip the network round-trip and the redundant content-control re-wrap
    // so the navigation is instant — this is the main 2x-wait fix.
    if (formFillingTemplate && formFillingTemplate.id === templateId) {
      log("[App] Re-entering existing form");
      setFormFillingSource("templateCreation");
      setViewMode("formFilling");
      setHasNavigated(true);
      return;
    }

    // Load the newly created template with variables and navigate to form filling
    setIsLoading(true);
    setError(null);

    try {
      log("[App] Loading newly created template for form filling");
      const loadedTemplate = await getTemplate(templateId);

      log(
        `[App] Loaded template "${loadedTemplate.name}" with ${loadedTemplate.variables.length} variables`
      );

      // Variables are already wrapped in Content Controls during the "Auto Detect Variables" step.
      // wrapVariablesWithBindingPlan short-circuits via getByTag when a CC for a tag
      // already exists, so calling it again would be a no-op anyway — but we skip
      // the re-call to keep the load-template path zero-write.

      // Tag each variable with whether it's actually bound to a content control
      // in the document. Ghost variables (AI-hallucinated originalText, or
      // substrings that live inside another wrapped variable) come back from
      // the DB but have no CC — the form needs to show them differently so
      // the user understands click→scroll/apply will only work for bound ones.
      const docCcTags = await getContentControlsInDocumentOrder();
      const docTagSet = new Set(docCcTags);
      const annotatedVars = loadedTemplate.variables.map((v: any) => ({
        ...v,
        hasContentControl: docTagSet.has(v.bindingId || v.name),
      }));
      const boundCount = annotatedVars.filter((v: any) => v.hasContentControl).length;
      log(
        `[App] Form variables: ${boundCount}/${annotatedVars.length} bound to content controls`
      );
      const unboundNames = annotatedVars
        .filter((v: any) => !v.hasContentControl)
        .map((v: any) => v.name);
      if (unboundNames.length > 0) {
        log(`[App] Unbound variable count: ${unboundNames.length}`);
      }

      // Store template data for form filling, sorted by document order
      const sortedVars = await sortVariablesByDocumentOrder(annotatedVars);
      setFormFillingTemplate({
        id: loadedTemplate.id,
        name: loadedTemplate.name,
        variables: sortedVars,
      });

      // Update selected template for consistency
      const newTemplate: Template = {
        id: loadedTemplate.id,
        name: loadedTemplate.name,
      };
      setSelectedTemplate(newTemplate);
      setTemplates((prev) => [...prev, newTemplate]);
      setRecentlyUsedTemplates((prev) => [newTemplate, ...prev].slice(0, 5));

      // Switch directly to form filling view
      setFormFillingSource("templateCreation");
      setViewMode("formFilling");
      setHasNavigated(true);
    } catch (error) {
      logError("[App] Template load failed", error);
      setError(
        error instanceof TemplateServiceException
          ? error.message
          : "Failed to load template from database. Please try again."
      );
      log(
        `[App] Error loading template: ${error instanceof Error ? error.message : "Unknown error"}`
      );
      // Fallback to template selector if loading fails
      setViewMode("templateSelector");
    } finally {
      setIsLoading(false);
    }
  };

  const handleTemplateSelectWithVariables = async (template: Template | null) => {
    // Just select the template, don't automatically load variables or switch screens
    // User will choose between "Auto Detect Variables" or "Fill the form"
    // But we need to fetch the actual variable count from the database
    if (!template) {
      handleTemplateSelect(null);
      return;
    }

    // Set template immediately so buttons are enabled
    handleTemplateSelect(template);

    // Fetch template to get actual variable count (async, doesn't block UI)
    setIsLoadingVariableCount(true);
    try {
      log("[App] Fetching template variable count");
      const loadedTemplate = await getTemplate(template.id);
      setPreviousVariablesCount(loadedTemplate.variables.length);
      log(
        `[App] Template "${template.name}" has ${loadedTemplate.variables.length} variables saved`
      );
    } catch (error) {
      logError("[App] Template variable-count load failed", error);
      // Set to null if we can't fetch, but still allow template selection
      setPreviousVariablesCount(null);
      warn("[App] Could not load template variable count");
    } finally {
      setIsLoadingVariableCount(false);
    }
  };



  const versionBanner = (
    <div className={styles.versionTag}>
      v{APP_VERSION} {BUILD_TIMESTAMP ? `(${new Date(BUILD_TIMESTAMP).toLocaleString()})` : ""}
    </div>
  );

  const draftSourceSelector = (mode: DraftSourceMode) => (
    <DraftSourceSelector
      value={mode}
      onChange={handleDraftSourceChange}
      savedTemplatesCount={templates.length}
      disabled={isLoading || creationDetecting}
    />
  );

  if (showDraftingWorkspace) {
    return (<Suspense fallback={<div className={styles.root}><Spinner size="large" label="Loading drafting workspace..." /></div>}><DraftingWorkspace onBack={() => setShowDraftingWorkspace(false)} /></Suspense>);
  }

  // Render form filling view if in formFilling mode
  if (viewMode === "formFilling" && formFillingTemplate) {
    const showBackButton = hasNavigated;

    return (
      <>
        {versionBanner}
        <Suspense
          fallback={
            <div
              className={styles.root}
              style={{
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                minHeight: "100vh",
              }}
            >
              <Spinner size="large" label="Loading form..." />
            </div>
          }
        >
          <FormFilling
            variables={isStreamingCreation ? streamingVariables : formFillingTemplate.variables}
            initialValues={formFillingTemplate.initialValues}
            templateName={formFillingTemplate.name}
            onBack={showBackButton ? handleBackFromFormFilling : undefined}
            onRenameVariable={handleRenameVariable}
            onApply={handleApplyVariableValues}
            onCompleteDrafting={handleCompleteDrafting}
            onSaveAsTemplate={!formFillingTemplate.id ? handleSaveCurrentDraftAsTemplate : undefined}
            onVerifyDraft={handleVerifyDraft}
            onDraftFinalized={handleDraftFinalized}
            onValuesChange={setLastKnownValues}
            docReady={docReady}
            streamError={streamErrorState}
            onAddVariable={async ({ name, originalText }) => {
              // Manually-added fields must become part of the SAVED reusable
              // template too — not just the current Word session.
              log("[App] Manual variable added");
              const templateId = formFillingTemplate.id;
              const manualBindingId = (() => {
                try {
                  return crypto.randomUUID();
                } catch {
                  return `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                }
              })();
              const candidate: Variable = {
                id: undefined,
                name,
                originalText,
                position: -1,
                confidenceScore: 1.0,
                bindingId: manualBindingId,
              };

              // Wrap in document FIRST — throw if not found so AddVariableForm shows error.
              const wrapStats = await wrapVariablesWithBindingPlan([candidate]);
              const manualTags = new Set(await getContentControlsInDocumentOrder());
              if (wrapStats.wrapped === 0 || !manualTags.has(manualBindingId)) {
                throw new Error(`Could not create and verify the Word field for "${originalText}". Select the intended text and try again.`);
              }

              if (!templateId) {
                const localVar: Variable = {
                  ...candidate,
                  id: manualBindingId,
                  hasContentControl: true,
                };
                const nextVariables = [...formFillingTemplate.variables, localVar];
                setFormFillingTemplate((prev) =>
                  prev ? { ...prev, variables: [...prev.variables, localVar] } : prev
                );
                try {
                  await syncAutoDraftBindingManifest(nextVariables, {});
                } catch (e) {
                  log(`[App] Unsaved draft manifest sync after manual field skipped: ${e instanceof Error ? e.message : e}`);
                }
                return;
              }

              const persisted = await addTemplateVariable(templateId, {
                name,
                originalText,
                position: -1,
                confidenceScore: 1.0,
                bindingId: manualBindingId,
              });
              const persistedVar: Variable = { ...persisted, hasContentControl: true };
              const nextVariables = [...formFillingTemplate.variables, persistedVar];
              try {
                await syncAutoDraftBindingManifest(nextVariables, { templateId });
              } catch (e) {
                log(`[App] Document manifest sync after manual field skipped: ${e instanceof Error ? e.message : e}`);
              }
              setFormFillingTemplate((prev) =>
                prev ? { ...prev, variables: [...prev.variables, persistedVar] } : prev
              );
              try {
                const cleanOoxml = await getReusableTemplateBodyOoxml(nextVariables);
                if (cleanOoxml) {
                  reusableTemplateSavePromiseRef.current = updateTemplateContent(templateId, cleanOoxml)
                    .then(() => true)
                    .catch((e) => {
                      log(`[App] Reusable template refresh after manual add failed: ${e instanceof Error ? e.message : e}`);
                      return false;
                    });
                }
              } catch (e) {
                reusableTemplateSavePromiseRef.current = Promise.resolve(false);
                log(`[App] Could not capture reusable template after manual add: ${e instanceof Error ? e.message : e}`);
              }
            }}
          />
        </Suspense>
      </>
    );
  }

  // Render template creation form if in creation mode
  if (viewMode === "templateCreation") {
    return (
      <>
        {versionBanner}
        <Suspense
          fallback={
            <div
              className={styles.root}
              style={{
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                minHeight: "100vh",
              }}
            >
              <Spinner size="large" label="Loading template form..." />
            </div>
          }
        >
          <div>
            <div style={{ padding: "12px 24px 0" }}><Button appearance="primary" onClick={() => setShowDraftingWorkspace(true)} style={{ width: "100%" }}>Open AI Drafting Workspace</Button></div>
            <TemplateCreationForm
            onSubmit={handleTemplateFormSubmit}
            sourceSelector={draftSourceSelector("own")}
            selectedTemplate={selectedTemplate}
            initialVariableResponse={identificationResponse}
            onAutoDetect={handleAutoDetectStreaming}
            isDetecting={creationDetecting}
            detectionError={creationDetectError}
          />
          </div>
        </Suspense>
      </>
    );
  }

  // Render saved-template selector view. The persistent source toggle replaces
  // the old menu/back-button hop and keeps both entry paths visible at all times.
  return (
    <div className={styles.root}>
      <div className={styles.versionTag}>
        v{APP_VERSION} {BUILD_TIMESTAMP ? `(${new Date(BUILD_TIMESTAMP).toLocaleString()})` : ""}
      </div>
      <h1 className={styles.title} style={{ marginBottom: "12px" }}>Start Draft</h1>
      {draftSourceSelector("saved")}
      <h2
        style={{
          margin: "4px 0 16px",
          fontSize: tokens.fontSizeBase500,
          fontWeight: tokens.fontWeightSemibold,
        }}
      >
        Choose a Saved Template
      </h2>
      <div className={styles.templateSection}>
        {isLoadingTemplates && (
          <div className={styles.loadingContainer} style={{ marginBottom: "12px" }}>
            <Spinner size="small" />
            <span className={styles.loadingText}>Loading saved templates...</span>
          </div>
        )}
        {templateListError && (
          <MessageBar intent="warning" style={{ marginBottom: "12px" }}>
            <MessageBarBody>{templateListError}</MessageBarBody>
          </MessageBar>
        )}
        <TemplateSelector
          templates={templates}
          recentlyUsedTemplates={recentlyUsedTemplates}
          onTemplateSelect={handleTemplateSelectWithVariables}
          allowCreate={false}
          label="Select a template"
        />


      </div>

      <div className={styles.buttonGroup}>
        <div className={styles.buttonContainer}>
          {/* Show loading indicator while fetching variable count */}
          {selectedTemplate && isLoadingVariableCount && (
            <div className={styles.loadingContainer} style={{ marginBottom: "16px" }}>
              <Spinner size="small" />
              <span className={styles.loadingText}>Loading variable count...</span>
            </div>
          )}

          {/* Show previous variables count if template is selected */}
          {selectedTemplate &&
            !isLoadingVariableCount &&
            previousVariablesCount !== null &&
            previousVariablesCount > 0 && (
              <div className={styles.variableCount} style={{ marginBottom: "16px" }}>
                <CheckmarkCircle24Filled className={styles.variableCountIcon} />
                <span>{previousVariablesCount} no of variables saved previously.</span>
              </div>
            )}

          {/* Loading Indicator */}
          {isLoading && (
            <div className={styles.loadingContainer}>
              <Spinner size="small" />
              <span className={styles.loadingText}>Identifying fields in your document...</span>
            </div>
          )}

          {/* Success: New Variables Count */}
          {!isLoading && identifiedVariablesCount !== null && identificationResponse && (
            <div style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" }}>
              <div className={styles.variableCount}>
                <CheckmarkCircle24Filled className={styles.variableCountIcon} />
                <span>{identifiedVariablesCount} no of new variables identified.</span>
              </div>
            </div>
          )}

          {/* AI Analysis Panel */}
          {!isLoading && identifiedVariablesCount !== null && identificationResponse && (
            <div style={{ marginTop: "16px" }}>
              <button
                onClick={() => setShowAnalysisPanel(!showAnalysisPanel)}
                style={{
                  width: "100%",
                  padding: "10px 16px",
                  borderRadius: tokens.borderRadiusMedium,
                  border: `1px solid ${tokens.colorNeutralStroke1}`,
                  backgroundColor: tokens.colorNeutralBackground2,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  fontSize: tokens.fontSizeBase300,
                  fontWeight: tokens.fontWeightSemibold,
                  color: tokens.colorNeutralForeground1,
                }}
              >
                <span>🤖 AI Document Analysis</span>
                {showAnalysisPanel ? <ChevronUp24Regular /> : <ChevronDown24Regular />}
              </button>

              {showAnalysisPanel && (
                <div style={{ marginTop: "8px" }}>
                  {/* Analysis Tab Bar */}
                  <div style={{ display: "flex", gap: "4px", marginBottom: "8px" }}>
                    {([
                      { key: "summary" as const, label: "Summary", icon: <DocumentSquare24Regular fontSize={14} /> },
                      { key: "risk" as const, label: "Risk", icon: <ShieldError24Regular fontSize={14} /> },
                      { key: "deadlines" as const, label: "Deadlines", icon: <CalendarClock24Regular fontSize={14} /> },
                    ]).map((tab) => (
                      <button
                        key={tab.key}
                        onClick={() => setAnalysisTab(tab.key)}
                        style={{
                          flex: 1,
                          padding: "6px 8px",
                          borderRadius: tokens.borderRadiusSmall,
                          border: `1px solid ${analysisTab === tab.key ? tokens.colorBrandStroke1 : tokens.colorNeutralStroke1}`,
                          backgroundColor: analysisTab === tab.key ? tokens.colorBrandBackground : tokens.colorNeutralBackground1,
                          color: analysisTab === tab.key ? tokens.colorNeutralForegroundOnBrand : tokens.colorNeutralForeground2,
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: "4px",
                          fontSize: tokens.fontSizeBase200,
                          fontWeight: tokens.fontWeightSemibold,
                        }}
                      >
                        {tab.icon}
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {/* Analysis Content */}
                  <Suspense fallback={<Spinner size="small" label="Loading..." />}>
                    {analysisTab === "summary" && (
                      <DocumentSummary documentContent={documentContentForAnalysis ?? undefined} />
                    )}
                    {analysisTab === "risk" && (
                      <RiskAssessment documentContent={documentContentForAnalysis ?? undefined} />
                    )}
                    {analysisTab === "deadlines" && (
                      <DeadlineTimeline documentContent={documentContentForAnalysis ?? undefined} />
                    )}
                  </Suspense>
                </div>
              )}
            </div>
          )}

          {/* Error Display */}
          {!isLoading && error && (
            <div className={styles.errorContainer}>
              <MessageBar intent="error">
                <MessageBarBody>
                  <div className={styles.errorMessage}>{error}</div>
                  <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                    <Button
                      appearance="secondary"
                      size="small"
                      onClick={handleRetry}
                      icon={<ArrowSync24Filled />}
                      className={styles.retryButton}
                    >
                      Retry
                    </Button>

                  </div>
                </MessageBarBody>
              </MessageBar>
            </div>
          )}
        </div>



        {selectedTemplate && (
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <Button
              appearance="subtle"
              disabled={templateActionBusy || isLoading}
              onClick={() => { setRenameTemplateValue(selectedTemplate.name); setShowRenameTemplateDialog(true); }}
            >
              Rename template
            </Button>
            <Button appearance="subtle" disabled={templateActionBusy || isLoading} onClick={()=>void handleDuplicateSelectedTemplate()}>
              Duplicate template
            </Button>
            <Button
              appearance="subtle"
              disabled={templateActionBusy || isLoading}
              onClick={() => setShowDeleteTemplateDialog(true)}
            >
              Delete template
            </Button>
          </div>
        )}

        <Button
          appearance="secondary"
          size="large"
          disabled={!selectedTemplate || isLoading}
          onClick={handleUseTemplate}
          className={styles.secondaryButton}
        >
          {isLoading ? "Loading..." : "Open saved template"}
        </Button>

        <Button
          appearance="secondary"
          size="large"
          disabled={!selectedTemplate || isLoading}
          onClick={handleFillForm}
          className={styles.secondaryButton}
        >
          Link fields in current document
        </Button>
      </div>

      <Dialog open={showRenameTemplateDialog} onOpenChange={(_e,d)=>{if(!templateActionBusy)setShowRenameTemplateDialog(d.open);}}>
        <DialogSurface><DialogBody><DialogTitle>Rename template</DialogTitle><DialogContent>
          <Input value={renameTemplateValue} onChange={(_e,d)=>setRenameTemplateValue(d.value)} style={{width:"100%"}} aria-label="Template name" />
        </DialogContent><DialogActions><Button onClick={()=>setShowRenameTemplateDialog(false)} disabled={templateActionBusy}>Cancel</Button><Button appearance="primary" onClick={()=>void handleRenameSelectedTemplate()} disabled={templateActionBusy||!renameTemplateValue.trim()}>{templateActionBusy?"Saving…":"Rename"}</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>

      <Dialog open={showDeleteTemplateDialog} onOpenChange={(_e,d)=>{if(!templateActionBusy)setShowDeleteTemplateDialog(d.open);}}>
        <DialogSurface><DialogBody><DialogTitle>Delete template?</DialogTitle><DialogContent>
          Delete {selectedTemplate ? `“${selectedTemplate.name}”` : "this template"} from Saved Templates? Existing Word documents are not deleted.
        </DialogContent><DialogActions><Button onClick={()=>setShowDeleteTemplateDialog(false)} disabled={templateActionBusy}>Cancel</Button><Button appearance="primary" onClick={()=>void handleDeleteSelectedTemplate()} disabled={templateActionBusy}>{templateActionBusy?"Deleting…":"Delete template"}</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>

      <Dialog open={showCaptureLayoutDialog} onOpenChange={(_e,d)=>{if(!captureLayoutBusy)setShowCaptureLayoutDialog(d.open);}}>
        <DialogSurface><DialogBody><DialogTitle>Reusable layout unavailable</DialogTitle><DialogContent>
          AutoDraft has the saved field definitions for {selectedTemplate ? `“${selectedTemplate.name}”` : "this template"}, but no reusable Word layout is stored. If the document currently open in Word is the correct clean template, AutoDraft can capture it as the reusable master without deleting your current document.
        </DialogContent><DialogActions><Button onClick={()=>setShowCaptureLayoutDialog(false)} disabled={captureLayoutBusy}>Cancel</Button><Button appearance="primary" onClick={()=>void handleCaptureCurrentDocumentAsTemplateLayout()} disabled={captureLayoutBusy}>{captureLayoutBusy?"Capturing…":"Capture current document"}</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </div>
  );
};

export default App;
