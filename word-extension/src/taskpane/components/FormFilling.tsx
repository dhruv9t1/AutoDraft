import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import {
  ArrowLeft24Regular,
  Checkmark24Regular,
  CheckmarkCircle16Filled,
  Dismiss24Regular,
  Warning16Filled,
} from "@fluentui/react-icons";
import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { scrollToContentControl, setContentControlColor } from "../../services/documentExtraction";
import { log } from "../../services/logger";
import { TemplateServiceException, updateVariable } from "../../services/templateService";
import AddVariableForm from "./AddVariableForm";
import { Variable, VerificationReport } from "../../services/types";

export interface FormFillingProps {
  variables: Variable[];
  initialValues?: Record<string, string>;
  templateName?: string;
  onBack?: () => void;
  onRenameVariable?: (variableId: string, oldName: string, newName: string) => Promise<Variable>;
  onApply?: (variableName: string, newValue: string, originalText?: string, bindingId?: string) => void;
  onCompleteDrafting?: () => Promise<void> | void;
  onSaveAsTemplate?: () => Promise<void> | void;
  onVerifyDraft?: () => Promise<VerificationReport>;
  onDraftFinalized?: () => void;
  onValuesChange?: (currentValues: Record<string, string>) => void;
  /** Called when the user manually adds a variable from the form. */
  onAddVariable?: (variable: { name: string; originalText: string }) => void;
  // Streaming-creation gate. While identification is still streaming the
  // content controls do not exist yet, so doc writes must be deferred and
  // typed values buffered. `docReady` flips false→true at finalize, triggering
  // a one-time flush of buffered values into the now-wrapped CCs.
  // Undefined defaults to live-write mode, so all existing callers are
  // byte-for-byte unchanged.
  docReady?: boolean;
  streamError?: string | null;
}

/** Whitespace-collapsed, lowercased normalization for stable cross-phase keys. */
function normKey(s: string): string {
  return s.trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * Stable identity for a variable that survives backend rename/disambiguation
 * between streamed chunks and the authoritative 'complete' list. originalText
 * is the only cross-phase-stable field (name and id can change); fall back to
 * id then name when originalText is empty.
 */
function stableKey(v: Variable): string {
  if (v.originalText && v.originalText.trim()) {
    return normKey(v.originalText);
  }
  return v.id || v.name;
}

/**
 * Read a buffered typed value for a variable, keyed ONLY by stableKey
 * (normalized originalText, falling back to id then name for empty-originalText
 * rows). A name-key fallback was intentionally removed: when a disambiguated
 * name gets REUSED for a different originalText (FE arrival-order vs BE
 * position-order swap), a normKey(name) lookup would return a DIFFERENT
 * variable's typed value and write it into the wrong CC. Returns undefined when
 * no stableKey-keyed value exists.
 */
function readBufferedValue(
  buffer: Record<string, string>,
  variable: Variable
): string | undefined {
  return buffer[stableKey(variable)];
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
    marginBottom: "24px",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "20px",
  },
  fieldLabel: {
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  errorMessage: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorPaletteRedForeground1,
    marginTop: "8px",
    padding: "12px 16px",
    backgroundColor: tokens.colorPaletteRedBackground1,
    borderRadius: tokens.borderRadiusMedium,
  },
  variableCount: {
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorNeutralForeground2,
    marginBottom: "16px",
    padding: "8px 12px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusMedium,
  },
  variableRow: {
    display: "flex",
    alignItems: "flex-end",
    gap: "8px",
    marginBottom: "20px",
  },
  variableInputContainer: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  variableNameInput: {
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  buttonGroupInline: {
    display: "flex",
    gap: "8px",
    alignItems: "center",
  },
  stickyFooter: {
    position: "sticky" as never,
    bottom: 0,
    padding: "16px 24px",
    backgroundColor: tokens.colorNeutralBackground1,
    borderTop: `1px solid ${tokens.colorNeutralStroke1}`,
    marginTop: "24px",
    marginLeft: "-24px",
    marginRight: "-24px",
    marginBottom: "-24px",
  },
  completeDraftingButton: {
    width: "100%",
    minHeight: "44px",
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  confidenceBadge: {
    display: "inline-flex",
    alignItems: "center",
    fontSize: "10px",
    fontWeight: tokens.fontWeightSemibold,
    padding: "1px 6px",
    borderRadius: tokens.borderRadiusCircular,
    lineHeight: "16px",
    letterSpacing: "0.3px",
    textTransform: "uppercase" as never,
    flexShrink: 0,
  },
  confidenceHigh: {
    backgroundColor: tokens.colorPaletteGreenBackground1,
    color: tokens.colorPaletteGreenForeground1,
    border: `1px solid ${tokens.colorPaletteGreenBorder1}`,
  },
  confidenceMedium: {
    backgroundColor: tokens.colorPaletteDarkOrangeBackground1,
    color: tokens.colorPaletteDarkOrangeForeground1,
    border: `1px solid ${tokens.colorPaletteDarkOrangeBorder1}`,
  },
  confidenceLow: {
    backgroundColor: tokens.colorPaletteRedBackground1,
    color: tokens.colorPaletteRedForeground1,
    border: `1px solid ${tokens.colorPaletteRedBorder1}`,
  },
});

const FormFilling: React.FC<FormFillingProps> = (props) => {
  const {
    variables,
    initialValues,
    templateName,
    onBack,
    onRenameVariable,
    onApply,
    onCompleteDrafting,
    onVerifyDraft,
    onDraftFinalized,
    onValuesChange,
    streamError,
    onAddVariable,
    onSaveAsTemplate,
  } = props;
  const styles = useStyles();
  // Undefined → true so every non-streaming caller keeps live-write semantics.
  // `ready` gates document operations until streaming reconciliation/wrapping
  // has completed. A fresh AutoDraft may still be intentionally unsaved here;
  // rename/manual-add use local state until explicit completion.
  const ready = props.docReady !== false;
  // Per-ROW doc-write readiness: a row's document ops (apply / focus color /
  // scroll / link marker) enable as soon as ITS content-control exists, even
  // while later rows are still streaming. Non-streaming callers leave docReady
  // undefined → rowReady true for every row → byte-for-byte unchanged behavior.
  const rowReady = (v: Variable): boolean =>
    props.docReady !== false || !!v.hasContentControl;

  const [variableValues, setVariableValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [editingVariableId, setEditingVariableId] = useState<string | null>(null);
  const [editingVariableName, setEditingVariableName] = useState<string>("");
  const [isSavingVariable, setIsSavingVariable] = useState<boolean>(false);
  const [variableNameMap, setVariableNameMap] = useState<Record<string, string>>({});
  const [isCompletingDraft, setIsCompletingDraft] = useState<boolean>(false);
  const [showCompleteDialog, setShowCompleteDialog] = useState<boolean>(false);
  const [showVerificationDialog, setShowVerificationDialog] = useState<boolean>(false);
  const [verificationReport, setVerificationReport] = useState<VerificationReport | null>(null);
  const [activeVariable, setActiveVariable] = useState<string | null>(null);
  const debounceTimersRef = useRef<Record<string, number>>({});
  // Buffer of typed values keyed by stableKey(originalText) so the growing/
  // renamed `variables` list never clobbers what the user typed during
  // streaming. Survives backend rename/disambiguation (same originalText key).
  const typedByKeyRef = useRef<Record<string, string>>({});
  // One-time TERMINAL flush guard: on docReady false→true we sweep any row whose
  // tag was never flushed per-batch (covers reconcile-renamed rows + value-loss).
  const hasFlushedRef = useRef<boolean>(false);
  // Per-tag flush guard for the PROGRESSIVE flush: each row replays its buffered
  // value into its content-control exactly once, the moment that CC appears.
  const flushedTagsRef = useRef<Set<string>>(new Set());
  // Live snapshot of the current (authoritative-at-flush-time) variables list,
  // read inside the [ready]-keyed flush effect without re-running per chunk.
  const variablesRef = useRef<Variable[]>(variables);
  variablesRef.current = variables;

  // Cleanup debounce timers on unmount
  useEffect(() => {
    return () => {
      (Object.values(debounceTimersRef.current) as number[]).forEach((t) => window.clearTimeout(t));
    };
  }, []);

  // Initialize variable values. Sourced from the typed-value buffer FIRST so
  // this effect is idempotent: a growing/renamed `variables` list (streaming)
  // only ADDS rows and never overwrites a value the user already typed.
  // For non-streaming callers the buffer is empty, so this reduces to the
  // previous initialValues/originalText logic (behavior-equivalent).
  React.useEffect(() => {
    const values: Record<string, string> = {};
    const nameMap: Record<string, string> = {};
    variables.forEach((variable) => {
      const key = variable.id || variable.name;
      const typed = readBufferedValue(typedByKeyRef.current, variable);
      const initVal = (initialValues && initialValues[variable.name]) || "";
      if (typed != null) {
        values[variable.name] = typed;
      } else if (initVal && initVal !== variable.name) {
        values[variable.name] = initVal;
      } else {
        values[variable.name] = variable.originalText || "";
      }
      if (key) {
        nameMap[key] = variable.name;
      }
    });
    setVariableValues(values);
    setVariableNameMap(nameMap);
    const filledCount = Object.values(values).filter((v) => v && v.trim()).length;
    log(
      `[FormFilling] Initialized form with ${variables.length} variables (${filledCount} pre-filled)`
    );
  }, [variables, initialValues]);

  // PROGRESSIVE per-tag flush: re-runs on every per-batch streamingVariables
  // annotate. As each row's content-control lands (rowReady true), replay its
  // buffered typed value into the CC exactly once. Typed values for not-yet-
  // wrapped rows stay buffered and flush when their CC appears in a later batch.
  // For non-streaming flows the buffer is empty, so the val guard makes this a
  // no-op (their values come FROM the doc — re-writing would be wrong).
  useEffect(() => {
    if (!onApply) {
      return;
    }
    (async () => {
      for (const v of variables) {
        if (!rowReady(v) || flushedTagsRef.current.has(v.name)) {
          continue;
        }
        const val = readBufferedValue(typedByKeyRef.current, v);
        if (val != null && val.trim() && val !== v.name && val !== v.originalText) {
          flushedTagsRef.current.add(v.name);
          try {
            // v.name === the CC tag the binding-plan wrapper wrote for this row.
            await onApply(v.name, val, v.originalText, v.bindingId);
          } catch (e) {
            flushedTagsRef.current.delete(v.name);
            log("[FormFilling] Progressive variable flush failed", e);
          }
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variables]);

  // TERMINAL flush: on docReady false→true (finalize wrapped the doc + created
  // the template) sweep any authoritative row whose tag was never flushed
  // per-batch (covers reconcile-renamed rows whose CC tag changed) and warn on
  // value-loss. Runs once. For non-streaming flows ready is true from mount and
  // the buffer is empty, so this is a no-op.
  useEffect(() => {
    if (!ready || hasFlushedRef.current || !onApply) {
      return;
    }
    hasFlushedRef.current = true;
    (async () => {
      for (const v of variablesRef.current) {
        // Primary stableKey, then name-key fallback — recovers values when
        // originalText diverged (or was empty) at reconcile time.
        const val = readBufferedValue(typedByKeyRef.current, v);
        if (val != null && val.trim() && val !== v.name && val !== v.originalText) {
          try {
            // v.name === the CC tag the binding-plan wrapper wrote.
            await onApply(v.name, val, v.originalText, v.bindingId);
          } catch (e) {
            log("[FormFilling] Variable flush failed", e);
          }
        }
      }
      // Observability: warn for any buffered non-empty value whose key matched
      // no authoritative variable at flush time, so the value-loss is visible
      // in the logs instead of silently dropped.
      const consumed = new Set<string>();
      variablesRef.current.forEach((v) => {
        consumed.add(stableKey(v));
        consumed.add(normKey(v.name));
      });
      Object.keys(typedByKeyRef.current).forEach((key) => {
        const buffered = typedByKeyRef.current[key];
        if (buffered != null && buffered.trim() && !consumed.has(key)) {
          log(
            `[FormFilling] Buffered value for key "${key}" found no authoritative match at flush — possible value loss: "${buffered}"`
          );
        }
      });
    })();
    // Run-once on the docReady false→true transition; onApply and refs are read
    // live (refs always current), so the effect intentionally keys only on `ready`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // Report current values back to parent whenever they change
  // This allows the parent to use these values when re-opening "Fill the form"
  useEffect(() => {
    if (onValuesChange && Object.keys(variableValues).length > 0) {
      onValuesChange(variableValues);
    }
  }, [variableValues, onValuesChange]);

  const handleInputFocus = async (variableName: string) => {
    // Until THIS row's CC exists, keep the active-field highlight but skip the
    // document color/scroll ops (per-row readiness, not all-or-nothing).
    const v = variables.find((x) => x.name === variableName);
    if (!v || !rowReady(v)) {
      setActiveVariable(variableName);
      return;
    }
    // Reset previous active variable to its proper color (green if filled, yellow if not)
    if (activeVariable && activeVariable !== variableName) {
      const prevValue = variableValues[activeVariable];
      const prevColor = prevValue && prevValue.trim() ? "#107C10" : "#FFFF00";
      const prevVar = variables.find((x) => x.name === activeVariable);
      setContentControlColor(prevVar?.bindingId || activeVariable, prevColor);
    }
    setActiveVariable(variableName);
    // Set active field to orange
    const controlTag = v.bindingId || variableName;
    await setContentControlColor(controlTag, "#E8600A");
    // Scroll document to this content control
    await scrollToContentControl(controlTag);
  };

  const handleInputBlur = async (variableName: string) => {
    const v = variables.find((x) => x.name === variableName);
    if (!v || !rowReady(v)) {
      if (activeVariable === variableName) {
        setActiveVariable(null);
      }
      return;
    }
    // Reset to proper color based on filled state
    const value = variableValues[variableName];
    const color = value && value.trim() ? "#107C10" : "#FFFF00";
    await setContentControlColor(v.bindingId || variableName, color);
    if (activeVariable === variableName) {
      setActiveVariable(null);
    }
  };

  const handleInputChange = (variableName: string, value: string) => {
    setVariableValues((prev) => ({
      ...prev,
      [variableName]: value,
    }));

    // Buffer the typed value keyed by stable identity (originalText) so it
    // survives backend rename/disambiguation and a growing `variables` list.
    // Keyed ONLY by stableKey — a name-key entry would cross-contaminate when a
    // disambiguated name is reused for a different originalText (arrival-vs-
    // position swap), feeding one variable's value into another's CC.
    const v = variables.find((x) => x.name === variableName);
    const primaryKey = v ? stableKey(v) : normKey(variableName);
    typedByKeyRef.current[primaryKey] = value;

    // Until THIS row's content-control exists, buffer only — never write to the
    // document (the progressive flush effect replays once the CC lands).
    if (!v || !rowReady(v)) {
      return;
    }

    window.clearTimeout(debounceTimersRef.current[variableName]);
    debounceTimersRef.current[variableName] = window.setTimeout(async () => {
      delete debounceTimersRef.current[variableName];
      if (onApply) {
        // Form → Document: dump value into the content control
        const currentVariable = variables.find((x) => x.name === variableName);
        await onApply(variableName, value, currentVariable?.originalText, currentVariable?.bindingId);
      }
    }, 500) as unknown as number;
  };

  const handleBack = () => {
    if (onBack) {
      onBack();
    }
  };

  const finishCompletion = async () => {
    if (!onCompleteDrafting) return;
    await onCompleteDrafting(); setError(null); setShowCompleteDialog(false); setShowVerificationDialog(false);
    log("[FormFilling] Drafting completed after verification — content controls removed");
    if (onDraftFinalized) onDraftFinalized();
  };
  const handleCompleteDrafting = async () => {
    if (!onCompleteDrafting || !ready) return; setIsCompletingDraft(true);
    try {
      if (onVerifyDraft) {
        const report=await onVerifyDraft(); setVerificationReport(report);
        if(report.status!=="pass"){setShowCompleteDialog(false);setShowVerificationDialog(true);return;}
      }
      await finishCompletion();
    } catch(err){log("[FormFilling] Error completing draft: "+String(err));setError(err instanceof Error?err.message:"Failed to complete drafting. Please try again.");}
    finally{setIsCompletingDraft(false);}
  };
  const proceedAfterVerificationReview = async () => {
    if(!verificationReport||verificationReport.blockers>0)return;setIsCompletingDraft(true);
    try{await finishCompletion();}catch(err){setError(err instanceof Error?err.message:"Failed to complete drafting.");}finally{setIsCompletingDraft(false);}
  };

  const handleStartEdit = (variable: Variable) => {
    // During streaming the template isn't persisted yet (id=""), so renaming a
    // variable would hit updateVariable with no row to update. Gate on `ready`,
    // mirroring the focus/blur/change/completeDrafting guards.
    if (!ready) {
      return;
    }
    const variableId = variable.id;
    if (!variableId) {
      setError("Cannot edit variable: missing variable ID. Variables must have a valid UUID.");
      log("[FormFilling] Cannot edit variable: missing ID");
      return;
    }
    setEditingVariableId(variableId);
    setEditingVariableName(variable.name);
    log("[FormFilling] Starting variable edit");
  };

  const handleCancelEdit = () => {
    setEditingVariableId(null);
    setEditingVariableName("");
    log(`[FormFilling] Cancelled edit`);
  };

  const handleSaveVariableName = async (variableId: string, oldName: string) => {
    // Streaming gate: the backend template isn't persisted yet (id=""), so
    // updateVariable would error. Mirror the other `!ready` guards.
    if (!ready) {
      return;
    }
    if (!variableId) {
      setError("Cannot update variable: missing variable ID");
      return;
    }

    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(variableId)) {
      setError(
        `Cannot update variable: invalid variable ID format. Variable ID must be a UUID, but got: ${variableId}`
      );
      log(`[FormFilling] Invalid variable ID format: ${variableId}`);
      return;
    }

    const newName = editingVariableName.trim();
    if (!newName) {
      setError("Variable name cannot be empty");
      return;
    }

    if (newName === oldName) {
      handleCancelEdit();
      return;
    }

    setIsSavingVariable(true);
    setError(null);

    try {
      log(
        `[FormFilling] Updating variable ${variableId} name from "${oldName}" to "${newName}"...`
      );
      const updatedVariable = onRenameVariable
        ? await onRenameVariable(variableId, oldName, newName)
        : await updateVariable(variableId, newName);

      setVariableNameMap((prev) => ({
        ...prev,
        [variableId]: updatedVariable.name,
      }));

      if (variableValues[oldName] !== undefined) {
        setVariableValues((prev) => {
          const newValues = { ...prev };
          newValues[updatedVariable.name] = newValues[oldName];
          delete newValues[oldName];
          return newValues;
        });
      }

      log("[FormFilling] Variable name updated");

      setEditingVariableId(null);
      setEditingVariableName("");
    } catch (err) {
      const errorMessage =
        err instanceof TemplateServiceException
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to update variable name";
      setError(errorMessage);
      log("[FormFilling] Variable-name update failed");
    } finally {
      setIsSavingVariable(false);
    }
  };

  const filledCount = variables.filter((v) => {
    const variableId = v.id || v.name;
    const currentName = variableNameMap[variableId] || v.name;
    const value = variableValues[currentName];
    return value && value.trim().length > 0;
  }).length;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>Fill the Form</h1>
        {onBack && (
          <Button
            appearance="subtle"
            icon={<ArrowLeft24Regular />}
            onClick={handleBack}
            className={styles.backButton}
          >
            Back
          </Button>
        )}
      </div>

      {variables.length > 0 && (
        <div className={styles.variableCount}>
          {filledCount} of {variables.length} variables filled
        </div>
      )}

      {streamError && <div className={styles.errorMessage}>{streamError}</div>}

      {error && <div className={styles.errorMessage}>{error}</div>}

      {onAddVariable && (
        <AddVariableForm
          onAdd={(v) => onAddVariable(v)}
          disabled={!ready || isCompletingDraft}
          linkLabel="+ Add another variable"
        />
      )}

      <div className={styles.form}>
        {variables.map((variable) => {
          const variableId = variable.id;
          const displayKey = variableId || variable.name;
          // Guard against undefined ids: streaming variables have no DB id yet,
          // so `editingVariableId === variableId` must NOT match when both are
          // nullish — otherwise every row would flip into the name-editor.
          const isEditing = !!variableId && editingVariableId === variableId;
          const currentName = variableNameMap[variableId || displayKey] || variable.name;

          return (
            <div key={displayKey} className={styles.variableRow}>
              <Field className={styles.variableInputContainer}>
                {isEditing ? (
                  <>
                    <Input
                      value={editingVariableName}
                      onChange={(e) => setEditingVariableName(e.target.value)}
                      placeholder="Enter variable name"
                      disabled={isSavingVariable || isCompletingDraft}
                      size="large"
                      className={styles.variableNameInput}
                      autoFocus
                    />
                    <div className={styles.buttonGroupInline} style={{ marginTop: "8px" }}>
                      <Button
                        appearance="primary"
                        icon={<Checkmark24Regular />}
                        onClick={() => {
                          if (variableId) {
                            handleSaveVariableName(variableId, currentName);
                          } else {
                            setError("Cannot save: Variable missing ID");
                          }
                        }}
                        disabled={
                          isSavingVariable ||
                          isCompletingDraft ||
                          !ready ||
                          !editingVariableName.trim() ||
                          !variableId
                        }
                        size="small"
                        title="Save variable name"
                      >
                        Save
                      </Button>
                      <Button
                        appearance="secondary"
                        icon={<Dismiss24Regular />}
                        onClick={handleCancelEdit}
                        disabled={isSavingVariable || isCompletingDraft}
                        size="small"
                        title="Cancel edit"
                      >
                        Cancel
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <label className={styles.fieldLabel}>
                      {currentName}
                      {!rowReady(variable) ? (
                        <span style={{fontSize:11,color:tokens.colorNeutralForeground3,fontWeight:400}}>Locating…</span>
                      ) : variable.reviewState === "needs_review" ? (
                        <span
                          title={`Semantic candidate kept for lawyer review and intentionally not auto-linked.${variable.reasonCodes?.length ? ` Evidence: ${variable.reasonCodes.join(", ")}` : ""}`}
                          aria-label="Semantic candidate needs review"
                          style={{display:"inline-flex",alignItems:"center",gap:3,color:tokens.colorPaletteDarkOrangeForeground1,fontSize:11,fontWeight:500}}
                        >
                          <Warning16Filled /> Check candidate
                        </span>
                      ) : variable.hasContentControl ? (
                        <span
                          title="Linked to the document — edits can sync to this Word field."
                          aria-label="Linked to document"
                          style={{display:"inline-flex",alignItems:"center",gap:3,color:tokens.colorPaletteGreenForeground1,fontSize:11,fontWeight:500}}
                        >
                          <CheckmarkCircle16Filled /> Linked
                        </span>
                      ) : (
                        <span
                          title="AutoDraft identified this field, but could not safely connect it to a Word range."
                          aria-label="Needs review"
                          style={{display:"inline-flex",alignItems:"center",gap:3,color:tokens.colorPaletteDarkOrangeForeground1,fontSize:11,fontWeight:500}}
                        >
                          <Warning16Filled /> Needs review
                        </span>
                      )}
                    </label>
                    <Input
                      value={variableValues[currentName] || ""}
                      onChange={(e) => handleInputChange(currentName, e.target.value)}
                      onFocus={() => handleInputFocus(currentName)}
                      onBlur={() => handleInputBlur(currentName)}
                      placeholder={
                        !rowReady(variable)
                          ? "Locating in document…"
                          : variable.reviewState === "needs_review"
                            ? "Review this candidate before manually linking it"
                          : variable.originalText
                            ? `eg: ${variable.originalText}`
                            : `Enter value for ${currentName}`
                      }
                      size="large"
                      // Editable only once the row is located in the document
                      // (its content-control exists → green marker). Until then
                      // the input is disabled. Non-streaming callers leave
                      // docReady undefined → rowReady true → always editable.
                      disabled={isCompletingDraft || !rowReady(variable) || variable.reviewState === "needs_review"}
                    />
                  </>
                )}
              </Field>
            </div>
          );
        })}
      </div>

      {onCompleteDrafting && (
        <div className={styles.stickyFooter}>
          <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
            {onSaveAsTemplate && (
              <Button
                appearance="secondary"
                size="large"
                onClick={async () => {
                  try { await onSaveAsTemplate(); setError(null); }
                  catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                }}
                disabled={isCompletingDraft || !ready}
              >
                Save reusable template
              </Button>
            )}
            <Button
              appearance="primary"
              size="large"
              className={styles.completeDraftingButton}
              onClick={() => setShowCompleteDialog(true)}
              disabled={isCompletingDraft || !ready}
              style={{ backgroundColor: "#E8600A", borderColor: "#E8600A" }}
            >
              {isCompletingDraft ? "Completing..." : !ready ? "Finishing identification…" : "Complete Drafting"}
            </Button>
          </div>

          <Dialog
            open={showCompleteDialog}
            onOpenChange={(_event, data) => {
              if (!isCompletingDraft) setShowCompleteDialog(data.open);
            }}
          >
            <DialogSurface>
              <DialogBody>
                <DialogTitle>Complete current document?</DialogTitle>
                <DialogContent>
                  <>
                    Complete this drafting session for the current Word document.
                    {templateName ? ` “${templateName}”` : ""} will only exist in Saved Templates if you explicitly saved it.
                    Completing the document does not create a reusable template.
                  </>
                </DialogContent>
                <DialogActions>
                  <Button
                    appearance="secondary"
                    disabled={isCompletingDraft}
                    onClick={() => setShowCompleteDialog(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    appearance="primary"
                    disabled={isCompletingDraft}
                    onClick={handleCompleteDrafting}
                    style={{ backgroundColor: "#E8600A", borderColor: "#E8600A" }}
                  >
                    {isCompletingDraft ? "Completing…" : "Complete document"}
                  </Button>
                </DialogActions>
              </DialogBody>
            </DialogSurface>
          </Dialog>
          <Dialog open={showVerificationDialog} onOpenChange={(_e,d)=>{if(!isCompletingDraft)setShowVerificationDialog(d.open);}}>
            <DialogSurface><DialogBody><DialogTitle>Document Review</DialogTitle><DialogContent>
              {verificationReport&&<div><p><b>{verificationReport.issues.length}</b> item{verificationReport.issues.length===1?"":"s"} to review. These findings are advisory and do not block completion.</p><div style={{maxHeight:"320px",overflowY:"auto"}}>{verificationReport.issues.map((issue,index)=><div key={index} style={{padding:"10px",marginBottom:"8px",borderRadius:"6px",background:issue.severity==="blocker"?"#fde7e9":issue.severity==="info"?"#f3f2f1":"#fff4ce"}}><div style={{fontSize:"11px",textTransform:"uppercase",color:"#666"}}>{issue.severity==="info"?"Information":"Needs attention"}</div><b>{issue.variableName||"Document review"}</b><br/>{issue.message}{issue.evidence&&<div style={{fontSize:"11px",color:"#666",marginTop:"4px"}}>{issue.evidence}</div>}</div>)}</div><p>Review the document and continue when you are satisfied with the result.</p></div>}
            </DialogContent><DialogActions><Button appearance="secondary" onClick={()=>setShowVerificationDialog(false)} disabled={isCompletingDraft}>Return to fields</Button>{verificationReport&&<Button appearance="primary" onClick={proceedAfterVerificationReview} disabled={isCompletingDraft}>{isCompletingDraft?"Completing…":"Complete after review"}</Button>}</DialogActions></DialogBody></DialogSurface>
          </Dialog>
        </div>
      )}
    </div>
  );
};

export default FormFilling;
