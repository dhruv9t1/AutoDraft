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
  CalendarClock24Regular,
  Alert24Regular,
  Clock24Regular,
} from "@fluentui/react-icons";
import * as React from "react";
import { useState } from "react";
import { getDeadlines } from "../../services/analysisService";
import { extractDocumentContent } from "../../services/documentExtraction";
import type { DeadlineResponse } from "../../services/types";
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
  deadlineItem: {
    display: "flex",
    gap: "10px",
    padding: "10px 12px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
    marginBottom: "6px",
    alignItems: "flex-start",
  },
  deadlineIcon: {
    flexShrink: 0,
    marginTop: "2px",
  },
  deadlineContent: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    flex: 1,
  },
  noticeItem: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    padding: "10px 12px",
    backgroundColor: tokens.colorNeutralBackground2,
    borderRadius: tokens.borderRadiusSmall,
    marginBottom: "6px",
  },
  noticeHeader: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    flexWrap: "wrap",
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
  urgencyCritical: {
    color: tokens.colorPaletteRedForeground1,
  },
  urgencyUrgent: {
    color: tokens.colorPaletteDarkOrangeForeground1,
  },
  urgencyNormal: {
    color: tokens.colorNeutralForeground2,
  },
});

interface DeadlineTimelineProps {
  documentContent?: string;
}

const DeadlineTimeline: React.FC<DeadlineTimelineProps> = ({ documentContent }) => {
  const styles = useStyles();
  const [deadlines, setDeadlines] = useState<DeadlineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExtract = async () => {
    setLoading(true);
    setError(null);
    setDeadlines(null);

    try {
      let content = documentContent;
      if (!content) {
        const doc = await extractDocumentContent();
        content = doc.text;
      }
      if (!content || content.trim().length === 0) {
        throw new Error("Document is empty");
      }

      const result = await getDeadlines(content);
      setDeadlines(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to extract deadlines";
      warn("[DeadlineTimeline] Request failed");
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const getUrgencyBadge = (urgency: string) => {
    const color =
      urgency === "critical" ? "danger" : urgency === "urgent" ? "warning" : "informative";
    return (
      <Badge appearance="filled" color={color} size="small">
        {urgency.toUpperCase()}
      </Badge>
    );
  };

  const getUrgencyIcon = (urgency: string) => {
    const color =
      urgency === "critical"
        ? tokens.colorPaletteRedForeground1
        : urgency === "urgent"
        ? tokens.colorPaletteDarkOrangeForeground1
        : tokens.colorNeutralForeground3;

    return <Clock24Regular fontSize={18} style={{ color }} />;
  };

  const totalDeadlines = deadlines ? deadlines.deadlines.length + deadlines.notices.length : 0;

  return (
    <div className={styles.root}>
      <Card className={styles.card}>
        <CardHeader
        header={<div style={{display: "flex", alignItems: "center", gap: "8px"}}><CalendarClock24Regular /><Body1Strong>Deadline Tracker</Body1Strong></div>}
          description={<Caption1>Extract deadlines, notice periods, and response dates</Caption1>}
        />
        <CardPreview>
          {!deadlines && !loading && !error && (
            <div style={{ padding: "8px 16px" }}>
              <Body1>
                Click below to extract all deadlines and notice periods from this document.
                Critical deadlines will be highlighted.
              </Body1>
            </div>
          )}

          {loading && (
            <div style={{ padding: "16px", textAlign: "center" }}>
              <Spinner size="small" label="Extracting deadlines..." />
            </div>
          )}

          {error && (
            <div style={{ padding: "8px 16px" }}>
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            </div>
          )}

          {deadlines && (
            <div style={{ padding: "8px 16px" }}>
              {/* Summary badge */}
              <div style={{ marginBottom: "8px" }}>
                <Badge appearance="outline" color="informative">
                  {totalDeadlines} deadline{totalDeadlines !== 1 ? "s" : ""} found
                </Badge>
              </div>

              {/* Deadlines */}
              {deadlines.deadlines.length > 0 && (
                <div>
                  <div className={styles.sectionLabel}>
                    <CalendarClock24Regular fontSize={14} />
                    <Caption1><strong>Deadlines</strong></Caption1>
                  </div>
                  {deadlines.deadlines.map((d, i) => (
                    <div key={i} className={styles.deadlineItem}>
                      <div className={styles.deadlineIcon}>{getUrgencyIcon(d.urgency)}</div>
                      <div className={styles.deadlineContent}>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                          <Body1Strong>{d.date}</Body1Strong>
                          {getUrgencyBadge(d.urgency)}
                        </div>
                        <Caption1>{d.description}</Caption1>
                        {d.daysRemaining !== null && (
                          <Caption1 className={styles.urgencyCritical}>
                            ⏱️ {d.daysRemaining} day{d.daysRemaining !== 1 ? "s" : ""} remaining
                          </Caption1>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Notices */}
              {deadlines.notices.length > 0 && (
                <div>
                  <div className={styles.sectionLabel}>
                    <Alert24Regular fontSize={14} />
                    <Caption1><strong>Notices</strong></Caption1>
                  </div>
                  {deadlines.notices.map((n, i) => (
                    <div key={i} className={styles.noticeItem}>
                      <div className={styles.noticeHeader}>
                        <Badge appearance="filled" color="brand" size="small">
                          {n.noticeType}
                        </Badge>
                        {n.legalSection && (
                          <Badge appearance="outline" size="small">
                            {n.legalSection}
                          </Badge>
                        )}
                      </div>
                      <Caption1>
                        <strong>Issued:</strong> {n.noticeDate}
                      </Caption1>
                      {n.responseDeadline && (
                        <Caption1>
                          <strong>Response due by:</strong>{" "}
                          <span className={styles.urgencyCritical}>{n.responseDeadline}</span>
                        </Caption1>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {totalDeadlines === 0 && (
                <div style={{ padding: "8px 0" }}>
                  <Body1>No deadlines or notices were found in this document.</Body1>
                </div>
              )}
            </div>
          )}
        </CardPreview>
        <CardFooter>
          <button
            className={styles.button}
            onClick={handleExtract}
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
            {loading ? "Extracting..." : deadlines ? "Re-extract" : "Extract Deadlines"}
          </button>
        </CardFooter>
      </Card>
    </div>
  );
};

export default DeadlineTimeline;
