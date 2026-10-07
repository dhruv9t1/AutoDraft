import {
  Button,
  Field,
  Input,
  ProgressBar,
  Spinner,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import { ArrowLeft24Regular } from "@fluentui/react-icons";
import * as React from "react";
import { useEffect, useRef, useState } from "react";
import {
  AiRetryExhaustedException,
  AiServiceException,
  AiTimeoutException,
  error as logError,
  extractDocumentContent,
  getDocumentFileName,
  getTemplate,
  identifyVariablesStreaming,
  identifyVariablesViaJob,
  log,
  supportsResponseStreaming,
  wrapVariablesWithBindingPlan,
} from "../../services";
import AddVariableForm from "./AddVariableForm";
import { OcrDependencyStatus, OcrJobResult, TemplateMetadata, Variable, VariableIdentificationResponse } from "../../services/types";
import { downloadSearchablePdf, getOcrStatus, processOcrFile } from "../../services/ocrService";
import { replaceDocumentWithOcrText } from "../../services/documentExtraction";

export interface TemplateCreationFormProps {
  onSubmit?: (metadata: TemplateMetadata, templateId?: string) => void;
  onBack?: () => void;
  /** Persistent source toggle supplied by App (My document / Saved template). */
  sourceSelector?: React.ReactNode;
  selectedTemplate?: { id: string; name: string } | null;
  initialVariableResponse?: VariableIdentificationResponse | null;
  // New-template (Auto Draft) streaming path: App owns the SSE stream and the
  // pre-navigation status. When selectedTemplate is null and onAutoDetect is
  // provided, the "Auto Detect Variables" button delegates to App, which
  // auto-navigates to the form on the first streamed chunk.
  onAutoDetect?: (metadata: TemplateMetadata) => void;
  isDetecting?: boolean;
  detectionError?: string | null;
}

const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    padding: "24px",
    backgroundColor: tokens.colorNeutralBackground1,
    minHeight: "100vh",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "24px",
    position: "relative",
  },
  backButton: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    color: tokens.colorNeutralForeground2,
    cursor: "pointer",
    "&:hover": {
      color: tokens.colorNeutralForeground1,
    },
  },
  title: {
    fontSize: tokens.fontSizeHero800,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    margin: 0,
  },
  subtitle: {
    fontSize: tokens.fontSizeBase400,
    color: tokens.colorNeutralForeground2,
    fontWeight: tokens.fontWeightRegular,
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "20px",
  },
  field: {
    width: "100%",
    "& label": {
      fontSize: tokens.fontSizeBase400,
      fontWeight: tokens.fontWeightSemibold,
      color: tokens.colorNeutralForeground1,
      marginBottom: "8px",
    },
  },
  input: {
    fontSize: tokens.fontSizeBase300,
  },
  buttonGroup: {
    display: "flex",
    gap: "12px",
    marginTop: "24px",
    width: "100%",
  },
  submitButton: {
    flex: 1,
    minHeight: "44px",
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  cancelButton: {
    flex: 1,
    minHeight: "44px",
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  autoDetectButton: {
    width: "100%",
    minHeight: "44px",
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    marginTop: "8px",
  },
  variableMessage: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorNeutralForeground1,
    marginTop: "16px",
    padding: "12px 16px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
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
  },
  detectionCard: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    padding: "14px 16px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    marginTop: "8px",
  },
  detectionHeader: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
  },
  detectionTitle: {
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    flex: 1,
  },
  detectionPercent: {
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorBrandForeground1,
    fontVariantNumeric: "tabular-nums",
  },
  detectionSubtext: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
  },
  detectionFoundPill: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorPaletteGreenForeground1,
    fontWeight: tokens.fontWeightSemibold,
  },
  errorMessage: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorPaletteRedForeground1,
    marginTop: "8px",
    padding: "12px 16px",
    backgroundColor: tokens.colorPaletteRedBackground1,
    borderRadius: tokens.borderRadiusMedium,
  },
  backgroundUploadBanner: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "10px 16px",
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusMedium,
    marginTop: "12px",
    border: `1px solid ${tokens.colorNeutralStroke1}`,
  },
  backgroundUploadSuccess: {
    backgroundColor: tokens.colorPaletteGreenBackground1,
    border: `1px solid ${tokens.colorPaletteGreenBorder1}`,
  },
  backgroundUploadError: {
    backgroundColor: tokens.colorPaletteRedBackground1,
    border: `1px solid ${tokens.colorPaletteRedBorder1}`,
  },
  backgroundUploadText: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground2,
    flex: 1,
  },
  backgroundUploadSuccessText: {
    color: tokens.colorPaletteGreenForeground1,
  },
  backgroundUploadErrorText: {
    color: tokens.colorPaletteRedForeground1,
  },
});

const TemplateCreationForm: React.FC<TemplateCreationFormProps> = (props) => {
  const {
    onSubmit,
    onBack,
    sourceSelector,
    selectedTemplate,
    initialVariableResponse,
    onAutoDetect,
  } = props;
  const styles = useStyles();
  // New-creation (Auto Draft) vs edit-existing-template branch. In the
  // new-creation branch, App owns the streaming detection + auto-navigation;
  // the local handleAutoDetectVariables / "Fill the form" submit are not used.
  const isNewCreation = !selectedTemplate;

  const [formData, setFormData] = useState<TemplateMetadata>({
    name: "",
    type: "",
    subtype: "",
    description: "",
  });

  const [errors, setErrors] = useState<Partial<Record<keyof TemplateMetadata, string>>>({});
  const [isDetectingVariables, setIsDetectingVariables] = useState<boolean>(false);
  const [isUpdatingFields, setIsUpdatingFields] = useState<boolean>(false);
  const [variableResponse, setVariableResponse] = useState<VariableIdentificationResponse | null>(
    null
  );
  const [variableError, setVariableError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Streaming progress (null when not streaming)
  const [streamProgress, setStreamProgress] = useState<{
    completed: number;
    total: number;
    foundSoFar: number;
  } | null>(null);
  // Background OOXML upload progress state
  const [backgroundUploadStatus, setBackgroundUploadStatus] = useState<{
    isUploading: boolean;
    stage: string;
    percentage: number;
    error: string | null;
  } | null>(null);
  const ocrInputRef = useRef<HTMLInputElement | null>(null);
  const ocrAbortRef = useRef<AbortController | null>(null);
  const [isOcrProcessing, setIsOcrProcessing] = useState(false);
  const [ocrResult, setOcrResult] = useState<OcrJobResult | null>(null);
  const [ocrError, setOcrError] = useState<string | null>(null);
  const [ocrStatus, setOcrStatus] = useState<OcrDependencyStatus | null>(null);
  const [isImportingOcr, setIsImportingOcr] = useState(false);
  useEffect(() => {
    if (!isNewCreation) return undefined;
    const controller = new AbortController();
    void getOcrStatus(controller.signal)
      .then(setOcrStatus)
      .catch(() => setOcrStatus(null));
    return () => controller.abort();
  }, [isNewCreation]);

  // Initialize form with selected template data if provided.
  // Also reloads variables from DB on remount (e.g. after Back from FormFilling)
  // so the "Fill the form" button stays enabled instead of waiting for the user
  // to re-run "Auto Detect Variables".
  useEffect(() => {
    if (!selectedTemplate) {
      return;
    }

    getTemplate(selectedTemplate.id)
      .then((template) => {
        setFormData({
          name: template.name,
          type: template.type,
          subtype: template.subtype,
          description: template.description,
        });
        if (initialVariableResponse) {
          setVariableResponse(initialVariableResponse);
          log(
            `[TemplateCreationForm] Initialized with template "${template.name}" and ${initialVariableResponse.variables.length} variables (from parent)`
          );
        } else if (template.variables && template.variables.length > 0) {
          setVariableResponse({
            variables: template.variables,
            identificationPercentage: 100,
            status: "completed",
            message: undefined,
          });
          log(
            `[TemplateCreationForm] Restored ${template.variables.length} variables from DB for template "${template.name}"`
          );
        }
      })
      .catch((error) => {
        logError("[TemplateCreation] Template data load failed", error);
        log(`[TemplateCreationForm] Warning: Failed to load template data: ${error}`);
        if (initialVariableResponse) {
          setVariableResponse(initialVariableResponse);
        }
      });
  }, [selectedTemplate, initialVariableResponse]);

  // Auto-detect template name from document file title
  useEffect(() => {
    if (!selectedTemplate) {
      const fileName = getDocumentFileName();
      if (fileName) {
        setFormData((prev) => ({ ...prev, name: fileName }));
        log("[TemplateCreationForm] Auto-detected template name from document filename");
      }
    }
  }, []);

  const handleInputChange = (field: keyof TemplateMetadata, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  const validateForm = (): boolean => {
    const newErrors: Partial<Record<keyof TemplateMetadata, string>> = {};

    if (!formData.name.trim()) {
      newErrors.name = "Template name is required";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const isFormValid = !!formData.name.trim();

  const handleOcrFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    ocrAbortRef.current?.abort();
    const controller = new AbortController();
    ocrAbortRef.current = controller;
    setOcrError(null);
    setOcrResult(null);
    setIsOcrProcessing(true);
    try {
      const result = await processOcrFile(file, controller.signal);
      setOcrResult(result);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setOcrError(error instanceof Error ? error.message : "OCR failed.");
      }
    } finally {
      if (ocrAbortRef.current === controller) ocrAbortRef.current = null;
      setIsOcrProcessing(false);
    }
  };

  const handleImportOcrText = async () => {
    if (!ocrResult?.text) return;
    if (!validateForm()) return;
    const confirmed = window.confirm(
      "Import OCR text into Word?\n\nThis replaces the current document body with the recognised Gujarati/English text so AutoDraft can identify and link fields. The generated searchable PDF remains available for download."
    );
    if (!confirmed) return;
    setIsImportingOcr(true);
    setOcrError(null);
    try {
      await replaceDocumentWithOcrText(ocrResult.text);
      if (isNewCreation && onAutoDetect) {
        await Promise.resolve(onAutoDetect(formData));
      } else {
        await handleAutoDetectVariables();
      }
    } catch (error) {
      setOcrError(error instanceof Error ? error.message : "Could not import OCR text into Word.");
    } finally {
      setIsImportingOcr(false);
    }
  };

  const handleAutoDetectVariables = async () => {
    if (!isFormValid) {
      return;
    }

    setIsDetectingVariables(true);
    setVariableError(null);
    setVariableResponse(null);
    setStreamProgress(null);

    try {
      // Check if running in Office context
      if (typeof Word === "undefined") {
        throw new Error(
          "Word API is not available. This add-in must be run within Microsoft Word."
        );
      }

      // Extract document content
      const documentContent = await extractDocumentContent();

      if (!documentContent.text || documentContent.text.trim().length === 0) {
        throw new Error(
          "Document is empty. Please add content to your document before detecting variables."
        );
      }

      // Call AI variable identification — prefer streaming when the runtime
      // supports it so the user sees variables appear as each chunk completes
      // instead of waiting 1–2 min for the whole batch.
      //
      // STREAMING UI ONLY: chunk_done events update the form panel so the
      // user sees variables appear as the BE finds them. The DOCUMENT WRAP
      // does NOT run progressively — it runs ONCE at stream complete using
      // the BE-supplied wrapping plan. This eliminates per-chunk Word.run
      // overhead, the cascade-poisoning that streaming wraps cause when a
      // child wraps before its parent, and all the FE-side dedup/filter
      // logic (the BE owns identification end-to-end now).
      let response: VariableIdentificationResponse;
      if (supportsResponseStreaming()) {
        log("[TemplateCreationForm] Using SSE streaming (UI-only progressive)");
        const found: Variable[] = [];

        response = await new Promise<VariableIdentificationResponse>((resolve, reject) => {
          identifyVariablesStreaming(
            documentContent.text,
            {
              onChunkDone: (_idx, total, vars) => {
                // BE owns dedup, list-marker filtering, and disambiguation —
                // we just append what the BE ships and refresh the panel.
                found.push(...vars);
                setStreamProgress((prev) => ({
                  completed: prev ? prev.completed : 0,
                  total,
                  foundSoFar: found.length,
                }));
                setVariableResponse({
                  variables: [...found],
                  identificationPercentage: 0,
                  status: "completed",
                  message: undefined,
                });
              },
              onProgress: (completed, total) => {
                setStreamProgress({ completed, total, foundSoFar: found.length });
              },
              onChunkError: (idx, msg) => {
                log(`[TemplateCreationForm] Chunk ${idx + 1} error: ${msg}`);
              },
              onComplete: (resp) => resolve(resp),
              onError: (err) => reject(err),
            },
            undefined,
            formData.name
          );
        });

        // Stream finished. The BE's complete-event payload is authoritative;
        // the running `found` accumulator was UI-only.
        setIsDetectingVariables(false);
        setStreamProgress(null);
        if (response.status === "unavailable" || response.status === "failed") {
          throw new Error(response.message || "Field detection could not be completed. The document was not modified.");
        }
        if (response.status === "no_fields") {
          setVariableResponse(response);
          return;
        }
        setIsUpdatingFields(true);
        try {
          // Build and commit the structural binding plan. Per-variable grounding
          // misses are skipped and reported; existing-binding integrity conflicts
          // remain blocking.
          if (response.variables && response.variables.length > 0) {
            log(
              `[TemplateCreationForm] Wrapping ${response.variables.length} variables via binding plan...`
            );
            try {
              const wrapStats = await wrapVariablesWithBindingPlan(response.variables);
              log(
                `[TemplateCreationForm] Wrap stats: ${wrapStats.wrapped}/${wrapStats.total} wrapped, ` +
                  `${wrapStats.missedFlat} missedFlat, ${wrapStats.errors} errors`
              );
            } catch (wrapError) {
              log(
                `[TemplateCreationForm] Warning: wrapVariablesWithBindingPlan failed: ${wrapError}`
              );
            }
          }
        } finally {
          setIsUpdatingFields(false);
        }
      } else {
        log("[TemplateCreationForm] Streaming unsupported — falling back to batch identifyVariables");
        response = await identifyVariablesViaJob(documentContent.text, undefined, formData.name);
        // Backend owns all filtering/dedup.

        // Batch path: single write at the end (original behavior).
        if (response.variables && response.variables.length > 0) {
          try {
            setIsUpdatingFields(true);
            log(
              `[TemplateCreationForm] Wrapping ${response.variables.length} variables via binding plan...`
            );
            const wrapStats = await wrapVariablesWithBindingPlan(response.variables);
            log(
              `[TemplateCreationForm] Wrap stats: ${wrapStats.wrapped}/${wrapStats.total} wrapped, ` +
                `${wrapStats.missedFlat} missedFlat, ${wrapStats.errors} errors`
            );
          } catch (replaceError) {
            logError("[TemplateCreation] Variable replacement failed", replaceError);
            log(
              `[TemplateCreationForm] Warning: Failed to replace variables in document: ${replaceError}`
            );
          } finally {
            setIsUpdatingFields(false);
          }
        }
      }

      // AI identification + writes are complete
      setIsDetectingVariables(false);
      setStreamProgress(null);
      setVariableResponse(response);


    } catch (error) {
      logError("[TemplateCreation] Variable detection failed", error);

      // Stop all loaders on error
      setIsDetectingVariables(false);
      setIsUpdatingFields(false);
      setStreamProgress(null);

      // Drop the partial per-chunk accumulator: it is not authoritative and a
      // failed run must be re-done. Clearing it hides the final-copy "We have
      // identified N" message (which would otherwise show a partial/aborted
      // count) and disables the CTA, matching the clean state at run start.
      setVariableResponse(null);

      if (error instanceof AiTimeoutException) {
        setVariableError(
          "Request timed out. The AI service took too long to respond. " + "Please try again."
        );
      } else if (error instanceof AiRetryExhaustedException) {
        setVariableError(
          "Unable to connect to AI service after multiple attempts. " +
            "Please check your connection and try again."
        );
      } else if (error instanceof AiServiceException) {
        setVariableError(error.message || "An error occurred while identifying variables.");
      } else if (error instanceof Error) {
        setVariableError(error.message || "An unexpected error occurred.");
      } else {
        setVariableError("An unknown error occurred. Please try again.");
      }
    }
  };

  const handleCreateTemplate = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm() || !variableResponse) {
      return;
    }

    // Edit-existing template path — the ONLY reachable branch of this handler.
    // The template already exists in the DB and its variables are loaded, so
    // re-running createTemplate would 409 on the duplicate name. Route straight
    // to FormFilling via onSubmit.
    //
    // New-creation (Auto Draft) no longer reaches the persistence path here:
    // App owns the streaming detection + auto-navigation and persists the
    // authoritative list itself, and the new-creation "Fill the form" submit
    // button is not rendered. Enter-submit on the new-creation form returns
    // above at `!variableResponse`. The old create/wrap/deferred machinery that
    // used to follow was therefore unreachable and has been removed.
    if (selectedTemplate) {
      log(
        `[TemplateCreationForm] Template "${selectedTemplate.name}" already exists (id=${selectedTemplate.id}); navigating to form filling`
      );
      if (onSubmit) {
        onSubmit(formData, selectedTemplate.id);
      }
    }
  };

  // Only show back button if we have a back handler (meaning user navigated here from another screen)
  const showBackButton = onBack !== undefined;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>
          {selectedTemplate ? "Edit Template" : "Auto Draft"}
        </h1>
        {showBackButton && onBack && (
          <Button
            appearance="subtle"
            icon={<ArrowLeft24Regular />}
            onClick={onBack}
            className={styles.backButton}
          >
            Back
          </Button>
        )}
      </div>
      <p className={styles.subtitle}>
        {selectedTemplate
          ? "Review and edit your template variables"
          : "Turn your current document into a standard template"}
      </p>

      {sourceSelector}

      <form onSubmit={handleCreateTemplate} className={styles.form}>
        <Field
          className={styles.field}
          label="Template Name"
          size="large"
          validationMessage={errors.name}
          validationState={errors.name ? "error" : "none"}
          required
        >
          <Input
            size="large"
            value={formData.name}
            onChange={(e) => handleInputChange("name", e.target.value)}
            placeholder="Enter template name"
            className={styles.input}
          />
        </Field>

        <Button
          appearance="secondary"
          size="large"
          onClick={
            isNewCreation && onAutoDetect
              ? () => {
                  if (validateForm()) {
                    onAutoDetect(formData);
                  }
                }
              : handleAutoDetectVariables
          }
          disabled={
            !isFormValid || (isNewCreation ? !!props.isDetecting : isDetectingVariables)
          }
          className={styles.autoDetectButton}
        >
          {(isNewCreation ? props.isDetecting : isDetectingVariables)
            ? "Scanning your document…"
            : "Auto Detect Variables"}
        </Button>

        {isNewCreation && (
          <div className={styles.detectionCard}>
            <div className={styles.detectionHeader}>
              <span className={styles.detectionTitle}>Scanned PDF / image</span>
              <span className={styles.detectionSubtext}>Gujarati + English OCR</span>
            </div>
            {ocrStatus && (
              <div className={styles.detectionSubtext}>
                {ocrStatus.ready
                  ? "✓ Local OCR ready (OCRmyPDF + Tesseract guj/eng)"
                  : `Local OCR needs setup${ocrStatus.missingLanguages.length ? ` — missing: ${ocrStatus.missingLanguages.join(", ")}` : ""}`}
              </div>
            )}
            <input
              ref={ocrInputRef}
              type="file"
              accept=".pdf,application/pdf,image/jpeg,image/png,image/tiff,.jpg,.jpeg,.png,.tif,.tiff"
              hidden
              onChange={handleOcrFileSelected}
            />
            <Button
              appearance="secondary"
              disabled={isOcrProcessing || isImportingOcr || !!props.isDetecting}
              onClick={() => ocrInputRef.current?.click()}
            >
              {isOcrProcessing ? "Running local OCR…" : "Import Scanned Document / OCR"}
            </Button>
            {isOcrProcessing && <Spinner size="small" label="Creating searchable PDF and recognised text…" />}
            {ocrError && <div className={styles.errorMessage}>{ocrError}</div>}
            {ocrResult?.status === "completed" && (
              <div className={styles.variableMessage}>
                <div>✓ OCR completed ({(ocrResult.languages || ["guj", "eng"]).join(" + ")})</div>
                <div>✓ {ocrResult.extractedCharacters || ocrResult.text?.length || 0} characters recognised</div>
                <div>✓ Searchable PDF generated</div>
                <div style={{ display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" }}>
                  <Button
                    appearance="primary"
                    disabled={isImportingOcr || !!props.isDetecting}
                    onClick={handleImportOcrText}
                  >
                    {isImportingOcr ? "Importing…" : "Import OCR Text into Word & Auto Draft"}
                  </Button>
                  <Button
                    appearance="secondary"
                    onClick={() => void downloadSearchablePdf(ocrResult.jobId, ocrResult.filename || "document.pdf")}
                  >
                    Download Searchable PDF
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* New-creation path: App owns the streaming state; we navigate to the
            form on the first chunk, so a simple scanning indicator suffices. */}
        {isNewCreation && props.isDetecting && (
          <div className={styles.loadingContainer}>
            <Spinner size="small" />
            <span className={styles.loadingText}>Scanning your document…</span>
          </div>
        )}

        {isNewCreation && props.detectionError && (
          <div className={styles.errorMessage}>{props.detectionError}</div>
        )}

        {!isNewCreation && isDetectingVariables && (() => {
          const total = streamProgress?.total ?? 0;
          const completed = streamProgress?.completed ?? 0;
          const foundSoFar = streamProgress?.foundSoFar ?? 0;
          const ratio = total > 0 ? Math.min(1, completed / total) : undefined;
          return (
            <div className={styles.detectionCard} role="status" aria-live="polite">
              <div className={styles.detectionHeader}>
                <Spinner size="tiny" />
                <span className={styles.detectionTitle}>
                  {foundSoFar > 0
                    ? `Found ${foundSoFar} field${foundSoFar === 1 ? "" : "s"} so far`
                    : "Looking through your document…"}
                </span>
              </div>
              <ProgressBar value={ratio} thickness="medium" />
              <div className={styles.detectionSubtext}>
                This usually takes less than a minute. You can keep this window open.
              </div>
            </div>
          );
        })()}

        {isUpdatingFields && (
          <div className={styles.loadingContainer}>
            <Spinner size="small" />
            <span className={styles.loadingText}>Updating fields with type...</span>
          </div>
        )}

        {variableError && <div className={styles.errorMessage}>{variableError}</div>}

        {saveError && (
          <div className={styles.errorMessage} style={{ marginTop: "16px" }}>
            {saveError}
          </div>
        )}

        {variableResponse && variableResponse.variables.length > 0 && (
          <>
            <div className={styles.variableMessage}>
              {isDetectingVariables ? (
                <>
                  Identified {variableResponse.variables.length} variable
                  {variableResponse.variables.length === 1 ? "" : "s"} so far — still scanning…
                </>
              ) : (
                <>
                  We have identified {variableResponse.variables.length} number of variables in the
                  document, kindly add or remove as per your requirement.
                </>
              )}
            </div>
            {!isDetectingVariables && (
              <AddVariableForm
                onAdd={async ({ name, originalText }) => {
                  // Build a new Variable from the manual form
                  const manualBindingId = (() => {
                    try {
                      return crypto.randomUUID();
                    } catch {
                      return `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                    }
                  })();
                  const newVar: Variable = {
                    id: manualBindingId,
                    name,
                    originalText,
                    position: -1,
                    confidenceScore: 1.0,
                    bindingId: manualBindingId,
                  };
                  // Ground and wrap it through the structural binding plan FIRST
                  const wrapStats = await wrapVariablesWithBindingPlan([newVar]);
                  if (wrapStats.wrapped === 0) {
                    throw new Error(`Could not find "${originalText}" in the document. Make sure the text appears exactly as shown.`);
                  }
                  // Add to the current variable list only if wrap succeeded
                  const updated = [...variableResponse!.variables, newVar];
                  const updatedResponse: VariableIdentificationResponse = {
                    ...variableResponse!,
                    variables: updated,
                  };
                  setVariableResponse(updatedResponse);
                }}
                disabled={isDetectingVariables || isUpdatingFields}
              />
            )}
          </>
        )}

        {/* Product decision: the "Fill the form" submit button is removed from
            the new-creation (Auto Draft) path — App auto-navigates to the form
            on the first streamed chunk. It still renders for edit-existing. */}
        {!isNewCreation && (
          <div className={styles.buttonGroup}>
            <Button
              appearance="primary"
              size="large"
              type="submit"
              disabled={
                isSaving ||
                isUpdatingFields ||
                isDetectingVariables ||
                !variableResponse ||
                variableResponse.variables.length === 0
              }
              className={styles.submitButton}
            >
              {isSaving ? "Saving..." : "Fill the form"}
            </Button>
          </div>
        )}

        {/* Background upload progress indicator */}
        {backgroundUploadStatus && (
          <div
            className={`${styles.backgroundUploadBanner} ${
              backgroundUploadStatus.error
                ? styles.backgroundUploadError
                : backgroundUploadStatus.percentage === 100
                  ? styles.backgroundUploadSuccess
                  : ""
            }`}
          >
            {backgroundUploadStatus.isUploading && <Spinner size="tiny" />}
            <span
              className={`${styles.backgroundUploadText} ${
                backgroundUploadStatus.error
                  ? styles.backgroundUploadErrorText
                  : backgroundUploadStatus.percentage === 100
                    ? styles.backgroundUploadSuccessText
                    : ""
              }`}
            >
              {backgroundUploadStatus.stage}
              {backgroundUploadStatus.isUploading && backgroundUploadStatus.percentage > 0 && (
                <> ({backgroundUploadStatus.percentage}%)</>
              )}
            </span>
          </div>
        )}
      </form>
    </div>
  );
};

export default TemplateCreationForm;
