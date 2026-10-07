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
import { ShieldError24Regular, Warning24Regular, Info24Regular } from "@fluentui/react-icons";
import * as React from "react";
import { useState } from "react";
import { getRiskAssessment } from "../../services/analysisService";
import { extractDocumentContent } from "../../services/documentExtraction";
import type { RiskAssessmentResponse } from "../../services/types";
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
  scoreContainer: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "12px 16px",
    marginBottom: "8px",
  },
  scoreCircle: {
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: tokens.fontSizeHero700,
    fontWeight: tokens.fontWeightBold,
    flexShrink: 0,
  },
  scoreHigh: {
    backgroundColor: tokens.colorPaletteRedBackground1,
    color: tokens.colorPaletteRedForeground1,
    border: `2px solid ${tokens.colorPaletteRedBorder1}`,
  },
  scoreMedium: {
    backgroundColor: tokens.colorPaletteDarkOrangeBackground1,
    color: tokens.colorPaletteDarkOrangeForeground1,
    border: `2px solid ${tokens.colorPaletteDarkOrangeBorder1}`,
  },
  scoreLow: {
    backgroundColor: tokens.colorPaletteGreenBackground1,
    color: tokens.colorPaletteGreenForeground1,
    border: `2px solid ${tokens.colorPaletteGreenBorder1}`,
  },
  factorItem: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    padding: "8px 12px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
    marginBottom: "4px",
  },
  factorHeader: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  issueItem: {
    display: "flex",
    alignItems: "flex-start",
    gap: "6px",
    padding: "6px 8px",
    backgroundColor: tokens.colorPaletteRedBackground1,
    borderRadius: tokens.borderRadiusSmall,
    marginBottom: "4px",
    fontSize: tokens.fontSizeBase200,
  },
  recItem: {
    display: "flex",
    alignItems: "flex-start",
    gap: "6px",
    padding: "6px 8px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
    marginBottom: "4px",
    fontSize: tokens.fontSizeBase200,
  },
  button: {
    width: "100%",
    marginTop: "8px",
  },
  sectionLabel: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginTop: "8px",
    marginBottom: "4px",
  },
});

interface RiskAssessmentProps {
  documentContent?: string;
}

const RiskAssessment: React.FC<RiskAssessmentProps> = ({ documentContent }) => {
  const styles = useStyles();
  const [assessment, setAssessment] = useState<RiskAssessmentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAssess = async () => {
    setLoading(true);
    setError(null);
    setAssessment(null);

    try {
      let content = documentContent;
      if (!content) {
        const doc = await extractDocumentContent();
        content = doc.text;
      }
      if (!content || content.trim().length === 0) {
        throw new Error("Document is empty");
      }

      const result = await getRiskAssessment(content);
      setAssessment(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to assess risk";
      warn("[RiskAssessment] Request failed");
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const getScoreStyle = (score: number) => {
    if (score >= 7) return styles.scoreHigh;
    if (score >= 4) return styles.scoreMedium;
    return styles.scoreLow;
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity.toLowerCase()) {
      case "high":
        return <ShieldError24Regular fontSize={14} style={{ color: tokens.colorPaletteRedForeground1 }} />;
      case "medium":
        return <Warning24Regular fontSize={14} style={{ color: tokens.colorPaletteDarkOrangeForeground1 }} />;
      default:
        return <Info24Regular fontSize={14} style={{ color: tokens.colorPaletteGreenForeground1 }} />;
    }
  };

  const getSeverityBadge = (severity: string) => {
    const color = severity === "high" ? "danger" : severity === "medium" ? "warning" : "informative";
    return <Badge appearance="outline" color={color} size="small">{severity}</Badge>;
  };

  return (
    <div className={styles.root}>
      <Card className={styles.card}>
        <CardHeader
        header={<div style={{display: "flex", alignItems: "center", gap: "8px"}}><ShieldError24Regular /><Body1Strong>Risk Assessment</Body1Strong></div>}
          description={<Caption1>AI-powered compliance and risk analysis</Caption1>}
        />
        <CardPreview>
          {!assessment && !loading && !error && (
            <div style={{ padding: "8px 16px" }}>
              <Body1>
                Click below to assess the risk level of this document. The AI will check for
                compliance issues, financial risks, and procedural concerns.
              </Body1>
            </div>
          )}

          {loading && (
            <div style={{ padding: "16px", textAlign: "center" }}>
              <Spinner size="small" label="Assessing risk..." />
            </div>
          )}

          {error && (
            <div style={{ padding: "8px 16px" }}>
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            </div>
          )}

          {assessment && (
            <div style={{ padding: "8px 16px" }}>
              {/* Score */}
              <div className={styles.scoreContainer}>
                <div className={`${styles.scoreCircle} ${getScoreStyle(assessment.riskScore)}`}>
                  {assessment.riskScore.toFixed(0)}
                </div>
                <div>
                  <Badge
                    appearance="filled"
                    color={assessment.overallRisk === "high" ? "danger" : assessment.overallRisk === "medium" ? "warning" : "success"}
                  >
                    {assessment.overallRisk.toUpperCase()} RISK
                  </Badge>
                  <Body1 style={{ marginTop: "4px" }}>
                    Overall risk score: {assessment.riskScore.toFixed(1)} / 10
                  </Body1>
                </div>
              </div>

              {/* Risk Factors */}
              {assessment.riskFactors.length > 0 && (
                <div>
                  <div className={styles.sectionLabel}>
                    <Warning24Regular fontSize={14} />
                    <Caption1><strong>Risk Factors</strong></Caption1>
                  </div>
                  {assessment.riskFactors.map((factor, i) => (
                    <div key={i} className={styles.factorItem}>
                      <div className={styles.factorHeader}>
                        {getSeverityIcon(factor.severity)}
                        <Body1Strong>{factor.category}</Body1Strong>
                        {getSeverityBadge(factor.severity)}
                      </div>
                      <Caption1>{factor.description}</Caption1>
                    </div>
                  ))}
                </div>
              )}

              {/* Compliance Issues */}
              {assessment.complianceIssues.length > 0 && (
                <div>
                  <div className={styles.sectionLabel}>
                    <ShieldError24Regular fontSize={14} />
                    <Caption1><strong>Compliance Issues</strong></Caption1>
                  </div>
                  {assessment.complianceIssues.map((issue, i) => (
                    <div key={i} className={styles.issueItem}>
                      <ShieldError24Regular fontSize={12} style={{ flexShrink: 0, marginTop: "2px" }} />
                      <Caption1>{issue}</Caption1>
                    </div>
                  ))}
                </div>
              )}

              {/* Recommendations */}
              {assessment.recommendations.length > 0 && (
                <div>
                  <div className={styles.sectionLabel}>
                    <Info24Regular fontSize={14} />
                    <Caption1><strong>Recommendations</strong></Caption1>
                  </div>
                  {assessment.recommendations.map((rec, i) => (
                    <div key={i} className={styles.recItem}>
                      <Info24Regular fontSize={12} style={{ flexShrink: 0, marginTop: "2px" }} />
                      <Caption1>{rec}</Caption1>
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
            onClick={handleAssess}
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
            {loading ? "Assessing..." : assessment ? "Re-assess" : "Assess Risk"}
          </button>
        </CardFooter>
      </Card>
    </div>
  );
};

export default RiskAssessment;
