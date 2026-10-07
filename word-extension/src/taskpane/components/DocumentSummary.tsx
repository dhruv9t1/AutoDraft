import {
  Card,
  CardHeader,
  CardPreview,
  CardFooter,
  Badge,
  Body1,
  Body1Strong,
  Caption1,
  Spinner,
  MessageBar,
  MessageBarBody,
  makeStyles,
  tokens,
} from "@fluentui/react-components";
import {
  DocumentSquare24Regular,
  Person24Regular,
  Calendar24Regular,
  Money24Regular,
  Shield24Regular,
} from "@fluentui/react-icons";
import * as React from "react";
import { useState } from "react";
import { getDocumentSummary } from "../../services/analysisService";
import { extractDocumentContent } from "../../services/documentExtraction";
import type { SummaryResponse } from "../../services/types";
import { log, warn } from "../../services/logger";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    padding: "16px",
  },
  card: {
    width: "100%",
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    marginBottom: "8px",
  },
  partyList: {
    display: "flex",
    flexWrap: "wrap",
    gap: "4px",
  },
  dateItem: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    padding: "6px 8px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
  },
  amountItem: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "4px 8px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
  },
  legalRef: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "4px 8px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
    fontSize: tokens.fontSizeBase200,
  },
  urgencyHigh: {
    color: tokens.colorPaletteRedForeground1,
    backgroundColor: tokens.colorPaletteRedBackground1,
    padding: "4px 12px",
    borderRadius: tokens.borderRadiusMedium,
  },
  urgencyMedium: {
    color: tokens.colorPaletteDarkOrangeForeground1,
    backgroundColor: tokens.colorPaletteDarkOrangeBackground1,
    padding: "4px 12px",
    borderRadius: tokens.borderRadiusMedium,
  },
  urgencyLow: {
    color: tokens.colorPaletteGreenForeground1,
    backgroundColor: tokens.colorPaletteGreenBackground1,
    padding: "4px 12px",
    borderRadius: tokens.borderRadiusMedium,
  },
  button: {
    width: "100%",
    marginTop: "8px",
  },
  summaryText: {
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    color: tokens.colorNeutralForeground2,
  },
  docType: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    marginBottom: "8px",
  },
  sectionLabel: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginTop: "8px",
    marginBottom: "4px",
  },
});

interface DocumentSummaryProps {
  /** Pre-extracted document content (optional — component extracts if not provided) */
  documentContent?: string;
}

const DocumentSummary: React.FC<DocumentSummaryProps> = ({ documentContent }) => {
  const styles = useStyles();
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    setSummary(null);

    try {
      let content = documentContent;
      if (!content) {
        const doc = await extractDocumentContent();
        content = doc.text;
      }

      if (!content || content.trim().length === 0) {
        throw new Error("Document is empty");
      }

      const result = await getDocumentSummary(content);
      setSummary(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to analyze document";
      warn("[DocumentSummary] Request failed");
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const getUrgencyStyle = (urgency: string) => {
    switch (urgency.toLowerCase()) {
      case "high":
        return styles.urgencyHigh;
      case "medium":
        return styles.urgencyMedium;
      default:
        return styles.urgencyLow;
    }
  };

  return (
    <div className={styles.root}>
      <Card className={styles.card}>
        <CardHeader
        header={<div style={{display: "flex", alignItems: "center", gap: "8px"}}><DocumentSquare24Regular /><Body1Strong>Document Summary</Body1Strong></div>}
          description={<Caption1>AI-powered document analysis</Caption1>}
        />
        <CardPreview>
          {!summary && !loading && !error && (
            <div style={{ padding: "8px 16px" }}>
              <Body1 className={styles.summaryText}>
                Click below to analyze this document. The AI will identify the document type,
                key parties, dates, amounts, and legal references.
              </Body1>
            </div>
          )}

          {loading && (
            <div style={{ padding: "16px", textAlign: "center" }}>
              <Spinner size="small" label="Analyzing document..." />
            </div>
          )}

          {error && (
            <div style={{ padding: "8px 16px" }}>
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            </div>
          )}

          {summary && (
            <div style={{ padding: "8px 16px" }}>
              {/* Document Type & Urgency */}
              <div className={styles.docType}>
                <Badge appearance="filled" color="brand">
                  {summary.documentType}
                </Badge>
                <span className={getUrgencyStyle(summary.urgency)}>
                  {summary.urgency.toUpperCase()} URGENCY
                </span>
              </div>

              {/* Summary */}
              <div className={styles.section}>
                <Body1 className={styles.summaryText}>{summary.summary}</Body1>
              </div>

              {/* Key Parties */}
              {summary.keyParties.length > 0 && (
                <div className={styles.section}>
                  <div className={styles.sectionLabel}>
                    <Person24Regular fontSize={14} />
                    <Caption1><strong>Key Parties</strong></Caption1>
                  </div>
                  <div className={styles.partyList}>
                    {summary.keyParties.map((party, i) => (
                      <Badge key={i} appearance="outline" size="small">
                        {party}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* Key Dates */}
              {summary.keyDates.length > 0 && (
                <div className={styles.section}>
                  <div className={styles.sectionLabel}>
                    <Calendar24Regular fontSize={14} />
                    <Caption1><strong>Key Dates</strong></Caption1>
                  </div>
                  {summary.keyDates.map((kd, i) => (
                    <div key={i} className={styles.dateItem}>
                      <Body1Strong>{kd.date}</Body1Strong>
                      <Caption1>{kd.context}</Caption1>
                    </div>
                  ))}
                </div>
              )}

              {/* Key Amounts */}
              {summary.keyAmounts.length > 0 && (
                <div className={styles.section}>
                  <div className={styles.sectionLabel}>
                    <Money24Regular fontSize={14} />
                    <Caption1><strong>Key Amounts</strong></Caption1>
                  </div>
                  {summary.keyAmounts.map((amt, i) => (
                    <div key={i} className={styles.amountItem}>
                      <Money24Regular fontSize={12} />
                      <Caption1>{amt}</Caption1>
                    </div>
                  ))}
                </div>
              )}

              {/* Legal References */}
              {summary.legalReferences.length > 0 && (
                <div className={styles.section}>
                  <div className={styles.sectionLabel}>
                    <Shield24Regular fontSize={14} />
                    <Caption1><strong>Legal References</strong></Caption1>
                  </div>
                  {summary.legalReferences.map((ref, i) => (
                    <div key={i} className={styles.legalRef}>
                      <Shield24Regular fontSize={10} />
                      <Caption1>{ref}</Caption1>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardPreview>
        <CardFooter>
          <button
            className={styles.button}
            onClick={handleAnalyze}
            disabled={loading}
            style={{
              padding: "8px 16px",
              borderRadius: tokens.borderRadiusMedium,
              border: `1px solid ${tokens.colorNeutralStroke1}`,
              backgroundColor: loading ? tokens.colorNeutralBackground3 : tokens.colorBrandBackground,
              color: loading ? tokens.colorNeutralForeground4 : tokens.colorNeutralForegroundOnBrand,
              cursor: loading ? "not-allowed" : "pointer",
              fontSize: tokens.fontSizeBase300,
              fontWeight: tokens.fontWeightSemibold,
            }}
          >
            {loading ? "Analyzing..." : summary ? "Re-analyze" : "Analyze Document"}
          </button>
        </CardFooter>
      </Card>
    </div>
  );
};

export default DocumentSummary;
