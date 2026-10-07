import { Button, makeStyles, tokens } from "@fluentui/react-components";
import * as React from "react";

export type DraftSourceMode = "own" | "saved";

export interface DraftSourceSelectorProps {
  value: DraftSourceMode;
  onChange: (mode: DraftSourceMode) => void;
  savedTemplatesCount?: number;
  disabled?: boolean;
}

const useStyles = makeStyles({
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    marginBottom: "20px",
  },
  label: {
    fontSize: tokens.fontSizeBase300,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  segmented: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "8px",
    padding: "4px",
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground2,
    border: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  button: {
    minHeight: "40px",
    whiteSpace: "normal",
    lineHeight: tokens.lineHeightBase200,
  },
  hint: {
    margin: 0,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase300,
    color: tokens.colorNeutralForeground3,
  },
});

const DraftSourceSelector: React.FC<DraftSourceSelectorProps> = ({
  value,
  onChange,
  savedTemplatesCount = 0,
  disabled = false,
}) => {
  const styles = useStyles();

  return (
    <div className={styles.container} aria-label="Choose how to start drafting">
      <div className={styles.label}>Start from</div>
      <div className={styles.segmented} role="group" aria-label="Draft source">
        <Button
          appearance={value === "own" ? "primary" : "subtle"}
          className={styles.button}
          disabled={disabled}
          aria-pressed={value === "own"}
          onClick={() => onChange("own")}
        >
          My document
        </Button>
        <Button
          appearance={value === "saved" ? "primary" : "subtle"}
          className={styles.button}
          disabled={disabled}
          aria-pressed={value === "saved"}
          onClick={() => onChange("saved")}
        >
          Saved template{savedTemplatesCount > 0 ? ` (${savedTemplatesCount})` : ""}
        </Button>
      </div>
      <p className={styles.hint}>
        {value === "own"
          ? "Use the document already open in Word and let AutoDraft identify its variable fields."
          : "Load a reusable empty template that was saved from an earlier draft."}
      </p>
    </div>
  );
};

export default DraftSourceSelector;
