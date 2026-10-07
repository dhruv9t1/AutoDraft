import {
  Button,
  Field,
  Input,
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import {
  Add24Regular,
  Dismiss24Regular,
  Checkmark24Regular,
} from "@fluentui/react-icons";
import * as React from "react";
import { useState } from "react";
import { Variable } from "../../services/types";

const useStyles = makeStyles({
  container: {
    marginTop: "12px",
    border: `1px dashed ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    padding: "16px",
    backgroundColor: tokens.colorNeutralBackground2,
    transition: "all 0.2s ease",
  },
  containerExpanded: {
    border: `1px solid ${tokens.colorBrandStroke1}`,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
  },
  toggleLink: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    fontSize: tokens.fontSizeBase300,
    color: tokens.colorBrandForeground1,
    fontWeight: tokens.fontWeightSemibold,
    cursor: "pointer",
    border: "none",
    background: "none",
    padding: "4px 0",
    transition: "color 0.15s ease",
    "&:hover": {
      color: tokens.colorBrandForeground2,
      textDecoration: "underline",
    },
    "&:focus-visible": {
      outline: `2px solid ${tokens.colorBrandStroke1}`,
      outlineOffset: "2px",
      borderRadius: tokens.borderRadiusSmall,
    },
  },
  toggleLinkLabel: {
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
  },
  formRow: {
    display: "flex",
    gap: "12px",
    marginTop: "12px",
    flexWrap: "wrap",
  },
  fieldWrapper: {
    flex: 1,
    minWidth: "200px",
  },
  fieldLabel: {
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground2,
    marginBottom: "4px",
  },
  actions: {
    display: "flex",
    gap: "8px",
    alignItems: "center",
    marginTop: "12px",
  },
  errorText: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorPaletteRedForeground1,
    marginTop: "8px",
  },
  successText: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorPaletteGreenForeground1,
    marginTop: "8px",
  },
  helperText: {
    fontSize: tokens.fontSizeBase200,
    color: tokens.colorNeutralForeground3,
  },
});

interface AddVariableFormProps {
  /** Called when the user submits a new variable. The parent is responsible for
   *  adding it to state, wrapping it in the doc, etc. */
  onAdd: (variable: { name: string; originalText: string }) => void;
  /** Called when the form is either closed or a variable was added, so the
   *  parent can e.g. re-sort the variable list. */
  onToggle?: (expanded: boolean) => void;
  /** Optional label override for the add link. */
  linkLabel?: string;
  /** Disable the form (e.g. during streaming / loading). */
  disabled?: boolean;
}

const AddVariableForm: React.FC<AddVariableFormProps> = ({
  onAdd,
  onToggle,
  linkLabel = "Add Variable",
  disabled = false,
}) => {
  const styles = useStyles();
  const [expanded, setExpanded] = useState(false);
  const [name, setName] = useState("");
  const [originalText, setOriginalText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);

  const handleToggle = () => {
    const next = !expanded;
    setExpanded(next);
    setError(null);
    setSuccess(null);
    if (onToggle) onToggle(next);
  };

  const handleCancel = () => {
    setExpanded(false);
    setName("");
    setOriginalText("");
    setError(null);
    setSuccess(null);
    if (onToggle) onToggle(false);
  };

  const handleAdd = async () => {
    const trimmedName = name.trim();
    const trimmedText = originalText.trim();

    // Validate
    if (!trimmedName) {
      setError("Variable name is required");
      return;
    }
    if (!trimmedText) {
      setError("Original text is required — enter the exact text from your document");
      return;
    }

    setIsAdding(true);
    setError(null);
    setSuccess(null);

    try {
      await onAdd({ name: trimmedName, originalText: trimmedText });
      setSuccess(`"${trimmedName}" added successfully`);
      setName("");
      setOriginalText("");
      // Auto-close after a short delay
      setTimeout(() => {
        setSuccess(null);
        setExpanded(false);
        if (onToggle) onToggle(false);
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add variable");
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div>
      {/* Toggle link */}
      {!expanded && (
        <button
          className={styles.toggleLink}
          onClick={handleToggle}
          disabled={disabled}
          type="button"
          aria-expanded="false"
        >
          <Add24Regular style={{ fontSize: "16px" }} />
          <span className={styles.toggleLinkLabel}>{linkLabel}</span>
        </button>
      )}

      {/* Expanded form */}
      {expanded && (
        <div className={`${styles.container} ${styles.containerExpanded}`}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Text weight="semibold" size={300}>
              Manually add a variable not found by AI
            </Text>
            <Button
              appearance="subtle"
              size="small"
              icon={<Dismiss24Regular />}
              onClick={handleCancel}
              disabled={isAdding}
              title="Close"
            />
          </div>

          <div className={styles.formRow}>
            <div className={styles.fieldWrapper}>
              <Field label="Variable Name" required size="small">
                <Input
                  value={name}
                  onChange={(e) => { setName(e.target.value); setError(null); }}
                  placeholder="e.g. Complainant Phone Number"
                  size="large"
                  disabled={isAdding}
                />
              </Field>
            </div>
            <div className={styles.fieldWrapper}>
              <Field label="Original Text" required size="small">
                <Input
                  value={originalText}
                  onChange={(e) => { setOriginalText(e.target.value); setError(null); }}
                  placeholder="e.g. 9876543210"
                  size="large"
                  disabled={isAdding}
                />
              </Field>
            </div>
          </div>

          <Text size={200} className={styles.helperText}>
            Enter the exact text as it appears in your document.
          </Text>

          <div className={styles.actions}>
            <Button
              appearance="primary"
              icon={<Checkmark24Regular />}
              onClick={handleAdd}
              disabled={isAdding || !name.trim() || !originalText.trim()}
              size="small"
            >
              {isAdding ? "Adding…" : "Add Variable"}
            </Button>
            <Button
              appearance="secondary"
              onClick={handleCancel}
              disabled={isAdding}
              size="small"
            >
              Cancel
            </Button>
          </div>

          {error && <div className={styles.errorText}>{error}</div>}
          {success && <div className={styles.successText}>{success}</div>}
        </div>
      )}
    </div>
  );
};

export default AddVariableForm;
