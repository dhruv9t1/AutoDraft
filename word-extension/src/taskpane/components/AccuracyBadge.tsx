import {
  Text,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import {
  CheckmarkCircle24Filled,
  Warning24Filled,
  ErrorCircle24Filled,
} from "@fluentui/react-icons";
import * as React from "react";

const useStyles = makeStyles({
  root: {
    display: "inline-flex",
    alignItems: "center",
    gap: "8px",
    padding: "4px 12px 4px 8px",
    borderRadius: tokens.borderRadiusCircular,
    lineHeight: tokens.lineHeightBase200,
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase200,
    fontVariantNumeric: "tabular-nums",
    transition: "all 0.3s ease",
  },
  highConfidence: {
    backgroundColor: tokens.colorPaletteGreenBackground1,
    color: tokens.colorPaletteGreenForeground1,
    border: `1px solid ${tokens.colorPaletteGreenBorder1}`,
  },
  mediumConfidence: {
    backgroundColor: tokens.colorPaletteDarkOrangeBackground1,
    color: tokens.colorPaletteDarkOrangeForeground1,
    border: `1px solid ${tokens.colorPaletteDarkOrangeBorder1}`,
  },
  lowConfidence: {
    backgroundColor: tokens.colorPaletteRedBackground1,
    color: tokens.colorPaletteRedForeground1,
    border: `1px solid ${tokens.colorPaletteRedBorder1}`,
  },
  icon: {
    display: "flex",
    alignItems: "center",
    flexShrink: 0,
  },
  percentage: {
    fontWeight: tokens.fontWeightBold,
    fontSize: tokens.fontSizeBase300,
  },
  label: {
    color: "inherit",
    fontWeight: tokens.fontWeightRegular,
    fontSize: tokens.fontSizeBase200,
    opacity: 0.9,
  },
});

interface AccuracyBadgeProps {
  /** Average extraction confidence from 0 to 100 (not measured recall). */
  percentage: number;
  /** Optional label override. Defaults to confidence level text. */
  label?: string;
  /** Optional class name override. */
  className?: string;
}

/** Color-coded confidence pill. This is model confidence, not measured accuracy/recall. */
const AccuracyBadge: React.FC<AccuracyBadgeProps> = ({ percentage, label, className }) => {
  const styles = useStyles();

  // Determine confidence tier
  const tier =
    percentage >= 80 ? "high" :
    percentage >= 50 ? "medium" :
    "low";

  const config = {
    high: {
      rootClass: styles.highConfidence,
      icon: <CheckmarkCircle24Filled style={{ fontSize: "16px" }} />,
      defaultLabel: label ?? "High confidence",
    },
    medium: {
      rootClass: styles.mediumConfidence,
      icon: <Warning24Filled style={{ fontSize: "16px" }} />,
      defaultLabel: label ?? "Medium confidence",
    },
    low: {
      rootClass: styles.lowConfidence,
      icon: <ErrorCircle24Filled style={{ fontSize: "16px" }} />,
      defaultLabel: label ?? "Low confidence",
    },
  }[tier];

  return (
    <span
      className={`${styles.root} ${config.rootClass}${className ? ` ${className}` : ""}`}
      role="status"
      aria-label={`AI confidence: ${percentage.toFixed(1)}% - ${config.defaultLabel}`}
      title={`${percentage.toFixed(1)}% AI confidence - ${config.defaultLabel}`}
    >
      <span className={styles.icon}>{config.icon}</span>
      <span className={styles.percentage}>{percentage.toFixed(1)}%</span>
      <Text size={200} className={styles.label}>
        {config.defaultLabel}
      </Text>
    </span>
  );
};

export default AccuracyBadge;
