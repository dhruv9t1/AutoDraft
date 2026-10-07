/**
 * Type definitions for AI Variable Identification
 * Following NestJS architecture pattern adapted for React/TypeScript
 */

export interface Variable {
  id?: string;
  name: string;
  originalText: string;
  position: number;
  confidenceScore?: number;
  currentValue?: string;
  bindingId?: string;
  anchorQuality?: "exact" | "normalized" | "not_found";
  sourceOccurrences?: number;
  grounded?: boolean;
  candidateId?: string;
  candidateKind?: string;
  candidateGroupId?: string;
  variants?: string[];
  repetitionCount?: number;
  classification?:
    "replaceable_value" | "static_text" | "heading" | "label" | "boilerplate" | "ambiguous";
  decisionSource?: "rule" | "system1" | "qwen" | "lawyer" | "unreviewed";
  reviewState?: "accepted" | "rejected" | "needs_review";
  reasonCodes?: string[];
  candidateEvidence?: Array<{ code: string; detail?: string; weight?: number }>;
  bindingState?: "bound" | "unbound" | "pending" | "binding_failed";
  // Set by App when handing variables to FormFilling. True when a content
  // control with this tag exists in the document right now — i.e. click→scroll
  // and form→doc apply will work. False for "ghost" rows the AI returned but
  // failed to wrap (hallucinated originalText, paraphrased text, or substring
  // overlap with another already-wrapped variable). Optional because the type
  // is also used at API boundaries that don't carry document state.
  hasContentControl?: boolean;
}

export interface VariableIdentificationRequest {
  documentContent: string;
  templateId?: string;
  templateName?: string;
  /** Previously-identified variables (from template DB or manual additions).
   *  The backend uses these as hints so the AI identifies them with higher
   *  confidence and less processing time. */
  knownVariables?: Variable[];
  segments?: Array<Record<string, unknown>>;
}

/**
 * Server-supplied wrapping plan: pre-computed search targets per variable so
 * the FE iterates verbatim instead of doing per-variable string processing.
 * Plan entries are ordered longest-original-text-first; `variableIndex` refers
 * to the corresponding `variables` array.
 *
 * See backend/app/wrapping.py for the source of truth.
 */
export interface WrappingPlanEntry {
  variableIndex: number;
  /** Single search string the FE issues to body.search. */
  searchText: string;
  /** True if `searchText` is a Word wildcard pattern. */
  useWildcards: boolean;
  /** Whether to paint visible `{` `}` around the wrapped span. False for
   * variables that will be absorbed by a parent (the parent's braces are the
   * only ones that should appear in the rendered doc). */
  insertBraces: boolean;
  /** When set, this variable's `originalText` is a strict substring of the
   * variable at `variables[absorbedBy]`. After all wraps complete, the FE
   * deletes this entry's CC so the document reads `{Parent ... Child ...}`
   * instead of nested `{Parent ... {Child} ...}`. */
  absorbedBy?: number;
}

/**
 * A hierarchical block of variables grouped by semantic category.
 *
 * - `Parent` blocks contain children that share a semantic relationship
 *   (e.g. all address fields under "Complete Address").
 * - `Atomic` blocks are standalone variables with no obvious siblings.
 */
/**
 * A hierarchical block of variables grouped by semantic category.
 *
 * The `type` discriminator (lowercase) matches the backend serde tag format.
 * - `"atomic"`: A standalone variable with no parent grouping.
 * - `"parent"`: A group of related variables under a parent label.
 */
export interface VariableBlock {
  /** Discriminator: "atomic" or "parent". Matches backend serde tag. */
  type: "atomic" | "parent";
  /** For atomic blocks: the single variable. */
  variable?: Variable;
  /** For parent blocks: a human-readable label (e.g. "Complete Address"). */
  label?: string;
  /** For parent blocks: child variables in document order. */
  children?: Variable[];
}

export interface VariableIdentificationResponse {
  variables: Variable[];
  /** Hierarchical grouping of variables for the frontend UI. */
  variableBlocks?: VariableBlock[];
  identificationPercentage: number;
  status: "completed" | "completed_with_review" | "no_fields" | "unavailable" | "failed";
  message?: string;
  /**
   * Backend-computed wrapping plan. Optional — older backends may omit it; the
   * FE falls back to local structural binding-plan computation.
   */
  wrappingPlan?: WrappingPlanEntry[];
  identificationMode?: "legal" | "general";
  coverageWarnings?: string[];
}

export interface ApiError {
  message: string;
  code?: string;
  statusCode?: number;
}

// ═══════════════════════════════════════════════════════════════════
// Analysis Types: Summary, Risk Assessment, Deadline Extraction
// ═══════════════════════════════════════════════════════════════════

export interface SummaryResponse {
  summary: string;
  documentType: string;
  keyParties: string[];
  keyDates: KeyDate[];
  keyAmounts: string[];
  legalReferences: string[];
  urgency: string;
}

export interface KeyDate {
  date: string;
  context: string;
}

export interface RiskAssessmentResponse {
  overallRisk: string;
  riskScore: number;
  riskFactors: RiskFactor[];
  complianceIssues: string[];
  recommendations: string[];
}

export interface RiskFactor {
  category: string;
  severity: string;
  description: string;
}

export interface DeadlineResponse {
  deadlines: Deadline[];
  notices: Notice[];
}

export interface Deadline {
  date: string;
  description: string;
  daysRemaining: number | null;
  urgency: string;
}

export interface Notice {
  noticeType: string;
  noticeDate: string;
  responseDeadline: string | null;
  legalSection: string | null;
}

/**
 * Template metadata for template creation form
 */
export interface TemplateMetadata {
  name: string;
  type: string;
  subtype: string;
  description: string;
}

export interface VerificationIssue {
  severity: "blocker" | "warning" | "info";
  code: string;
  message: string;
  variableName?: string | null;
  evidence?: string | null;
}
export interface VerificationReport {
  status: "pass" | "review" | "block";
  issues: VerificationIssue[];
  blockers: number;
  warnings: number;
  checkedVariables: number;
}
export type IntakeQuestionType =
  | "text"
  | "textarea"
  | "date"
  | "number"
  | "currency"
  | "email"
  | "phone"
  | "select"
  | "boolean"
  | "address"
  | "person"
  | "multi_select"
  | "file";
export interface IntakeDisplayRule {
  questionId: string;
  operator: "equals" | "not_equals" | "exists" | "not_exists" | "contains";
  value?: string;
}
export interface IntakeValidation {
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  allowedExtensions?: string[];
  minValue?: number;
  maxValue?: number;
}
export interface IntakeSection {
  id: string;
  title: string;
  description?: string;
  position: number;
}
export interface IntakeQuestion {
  id: string;
  label: string;
  type: IntakeQuestionType;
  required: boolean;
  options: string[];
  mapsTo: string;
  helpText: string;
  approved: boolean;
  sectionId?: string | null;
  position?: number;
  displayRule?: IntakeDisplayRule | null;
  validation?: IntakeValidation;
}
export interface IntakeDefinition {
  id?: string;
  version?: number;
  status?: "draft" | "published" | "retired" | string;
  title: string;
  matterType: string;
  sections?: IntakeSection[];
  questions: IntakeQuestion[];
}

export interface MatterSummary {
  id: string;
  title: string;
  matterType: string;
  status: string;
  referenceCode?: string;
  practiceAreaId?: string | null;
  practiceAreaName?: string | null;
  stageId?: string | null;
  stageName?: string | null;
  stageChangedAt?: string | null;
  primaryClientName?: string | null;
  createdAt?: string;
  updatedAt?: string;
}
export interface MatterFact {
  id?: string;
  field: string;
  label?: string;
  fact: string;
  fact_key?: string;
  value_type?: string;
  source?: string;
  status?: string;
  is_canonical?: boolean;
  derived_from?: string[];
  created_at?: string;
}
export interface MatterAuthority {
  id: string;
  title: string;
  citation: string;
  source_url?: string;
  sourceUrl?: string;
  verified: boolean;
  created_at?: string;
}
export interface MatterDocument {
  id: string;
  matter_id?: string;
  name: string;
  mime_type?: string;
  source?: string;
  metadata?: Record<string, unknown>;
  sha256?: string;
  size_bytes?: number;
  created_at?: string;
  updated_at?: string;
}
export interface FactConflict {
  id: string;
  fact_key?: string;
  status: string;
  resolution_fact_id?: string | null;
  candidates: MatterFact[];
  created_at?: string;
  resolved_at?: string | null;
}
export interface MatterDetail extends MatterSummary {
  facts: MatterFact[];
  canonicalValues?: CanonicalFieldValue[];
  participants?: MatterParticipant[];
  authorities: MatterAuthority[];
  conflicts?: FactConflict[];
  documents?: MatterDocument[];
}
export type ReviewCategory =
  | "missing_information"
  | "field_connection"
  | "document_consistency"
  | "drafting"
  | "authority"
  | "formatting";
export type ReviewSeverity = "information" | "review" | "important";
export interface DraftReviewFinding {
  id: string;
  category: ReviewCategory;
  severity: ReviewSeverity;
  title: string;
  detail: string;
  suggestedAction?: string | null;
  location?: {
    searchText?: string;
    quote?: string;
    paragraphIndex?: number;
    [key: string]: unknown;
  } | null;
}
export type CitationReviewStatus =
  "not_applicable" | "not_checked" | "needs_verification" | "partially_verified" | "verified";
export interface CitationVerification {
  status: CitationReviewStatus | string;
  authorityCount?: number;
  verifiedAuthorityCount?: number;
  detectedCitationCount?: number;
  supportedCitations?: string[];
  unsupportedCitations?: string[];
  removedSyntheticSourceMarkers?: string[];
}
export interface DraftingResponse {
  answer: string;
  draft: string;
  sections: string[];
  questions: string[];
  assumptions: string[];
  authoritiesUsed: Array<Record<string, unknown>>;
  factLedger?: Array<Record<string, unknown>>;
  citationVerification?: CitationVerification;
  qaIssues?: DraftReviewFinding[];
  reviewFindings?: DraftReviewFinding[];
  missingInformation?: Array<{ key?: string; label?: string; question?: string; reason?: string }>;
  citationStatus?: CitationReviewStatus | string;
  plan?: Record<string, unknown>;
}
export type DraftingMode = "answer" | "complete_document";

export type OcrJobState = "running" | "completed" | "failed" | "cancelled";
export interface OcrJobResult {
  jobId: string;
  status: OcrJobState;
  error?: string | null;
  filename?: string;
  pages?: number | null;
  ocrPerformed?: boolean | null;
  hadCompleteTextLayer?: boolean | null;
  languages?: string[];
  extractedCharacters?: number;
  text?: string;
  createdAt?: string;
}
export interface OcrDependencyStatus {
  ready: boolean;
  ocrmypdf: boolean;
  tesseract: boolean;
  installedLanguages: string[];
  missingLanguages: string[];
  requiredLanguages: string[];
}

// ═══════════════════════════════════════════════════════════════════
// Clio-inspired canonical legal data
// ═══════════════════════════════════════════════════════════════════
export interface PracticeArea {
  id: string;
  key: string;
  name: string;
  description: string;
  position: number;
  active: boolean;
}
export interface MatterStage {
  id: string;
  practiceAreaId?: string | null;
  key: string;
  name: string;
  description: string;
  position: number;
  active: boolean;
}
export interface Contact {
  id: string;
  contactType: "person" | "company";
  displayName: string;
  firstName: string;
  middleName: string;
  lastName: string;
  companyName: string;
  email: string;
  phone: string;
  metadata?: Record<string, unknown>;
}
export interface MatterParticipant {
  id: string;
  matterId: string;
  contactId: string;
  roleKey: string;
  displayRole: string;
  isClient: boolean;
  isPrimary: boolean;
  representedByFirm: boolean;
  position: number;
  metadata?: Record<string, unknown>;
  contact: Contact;
}
export interface FieldGroup {
  id: string;
  key: string;
  label: string;
  entityScope: "matter" | "contact";
  roleKey?: string | null;
  practiceAreaId?: string | null;
  practiceAreaName?: string | null;
  position: number;
}
export type CanonicalFieldValueType =
  | "text"
  | "long_text"
  | "integer"
  | "decimal"
  | "currency"
  | "date"
  | "datetime"
  | "boolean"
  | "choice"
  | "multi_choice"
  | "email"
  | "phone"
  | "address"
  | "contact_reference"
  | "matter_reference"
  | "document_reference"
  | "json";
export interface FieldDefinition {
  id: string;
  semanticKey: string;
  displayLabel: string;
  description: string;
  entityScope: "matter" | "contact";
  valueType: CanonicalFieldValueType;
  repeatable: boolean;
  required: boolean;
  validation: Record<string, unknown>;
  formatting: Record<string, unknown>;
  options: unknown[];
  aliases: string[];
  groupId?: string | null;
  groupKey?: string | null;
  groupLabel?: string | null;
  groupRoleKey?: string | null;
  practiceAreaId?: string | null;
  matterType: string;
  position: number;
  active: boolean;
}
export interface CanonicalFieldValueItem {
  id: string;
  position: number;
  value: unknown;
  source: string;
  status: string;
  provenance: Record<string, unknown>;
}
export interface CanonicalFieldValue {
  id: string;
  fieldDefinitionId: string;
  semanticKey: string;
  displayLabel: string;
  valueType: CanonicalFieldValueType;
  repeatable?: boolean;
  value: unknown;
  items?: CanonicalFieldValueItem[];
  rawText?: string | null;
  source: string;
  status: string;
  provenance: Record<string, unknown>;
  groupKey?: string | null;
  groupLabel?: string | null;
  groupRoleKey?: string | null;
  updatedAt?: string;
}
export interface DocumentSetSummary {
  id: string;
  name: string;
  description: string;
  practiceAreaId?: string | null;
  practiceAreaName?: string | null;
  matterType: string;
  status: "draft" | "published" | "retired" | string;
  currentVersion: number;
  draftItemCount: number;
}
export interface DocumentSetDraftItem {
  id: string;
  templateId: string;
  templateName: string;
  label: string;
  position: number;
  required: boolean;
  metadata: Record<string, unknown>;
  currentTemplateVersion: number;
  hasFullDocx: boolean;
  snapshotKind: string;
}
export interface DocumentSetVersion {
  id: string;
  versionNumber: number;
  status: string;
  publishedAt: string;
}
export interface DocumentSetDetail {
  documentSet: DocumentSetSummary;
  draftItems: DocumentSetDraftItem[];
  versions: DocumentSetVersion[];
}
export interface MatterActivityEvent {
  id: string;
  eventType: string;
  aggregateType: string;
  aggregateId?: string | null;
  payload: Record<string, unknown>;
  status: string;
  createdAt: string;
}

export interface DocumentSetPublishedItem {
  id: string;
  templateId: string;
  templateName: string;
  templateVersionId: string;
  templateVersion: number;
  label: string;
  position: number;
  required: boolean;
  metadata: Record<string, unknown>;
}
export interface GenerationRun {
  id: string;
  matterId: string;
  documentSetVersionId?: string;
  status: "selection" | "population" | "review" | "completed" | "failed" | string;
  selectedItems: string[];
  metadata?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
}

// ═══════════════════════════════════════════════════════════════════
// Gavel-inspired workflow/document automation
// ═══════════════════════════════════════════════════════════════════
export type AutomationExpression = unknown;
export interface WorkflowQuestion {
  id: string;
  label: string;
  semanticKey: string;
  type: string;
  required?: boolean;
  helpText?: string;
  options?: unknown[];
  validation?: Record<string, unknown>;
  condition?: AutomationExpression;
  minItems?: number;
  maxItems?: number;
  itemScoped?: boolean;
  children?: WorkflowQuestion[];
}
export interface WorkflowPage {
  id: string;
  title: string;
  description?: string;
  condition?: AutomationExpression;
  questions: WorkflowQuestion[];
}
export interface WorkflowCalculation {
  key: string;
  label?: string;
  expression: AutomationExpression;
  condition?: AutomationExpression;
  fallback?: unknown;
  valueType?: string;
}
export interface WorkflowDefinition {
  pages: WorkflowPage[];
  calculations: WorkflowCalculation[];
}
export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  audience: "internal" | "client" | "both";
  practiceAreaId?: string | null;
  matterType: string;
  status: string;
  currentVersion: number;
}
export interface WorkflowVersion {
  id: string;
  workflowId: string;
  version: number;
  status: string;
  definition?: WorkflowDefinition;
  publishedAt?: string | null;
  createdAt: string;
}
export interface WorkflowSession {
  id: string;
  workflowVersionId: string;
  matterId?: string | null;
  status: string;
  answers: Record<string, unknown>;
  calculations: Record<string, unknown>;
  currentPage?: string | null;
  metadata: Record<string, unknown>;
  expiresAt?: string | null;
  completedAt?: string | null;
}
export interface WorkflowEvaluation {
  calculations: Record<string, unknown>;
  visiblePages: WorkflowPage[];
  missingRequired: Array<Record<string, unknown>>;
  complete: boolean;
}
export interface TemplateAutomationBlueprint {
  bindings: Array<{
    controlTag: string;
    semanticKey?: string;
    expression?: AutomationExpression;
    formatting?: Record<string, unknown>;
  }>;
  conditions: Array<{ regionTag: string; expression: AutomationExpression }>;
  repeaters: Array<{
    regionTag: string;
    collectionKey?: string;
    collectionExpression?: AutomationExpression;
    condition?: AutomationExpression;
    itemAlias?: string;
  }>;
  retainControls?: boolean;
}
export interface TemplateAutomationPreflight {
  ready: boolean;
  issues: Array<{
    severity: "error" | "warning" | string;
    code: string;
    message: string;
    tag?: string;
  }>;
  tagCounts: Record<string, number>;
  templateVersion?: number;
  templateVersionId?: string | null;
}
export interface HeadlessArtifact {
  id: string;
  matterDocumentId?: string | null;
  templateId: string;
  templateVersion: number;
  filename: string;
  mimeType: string;
  docxBase64: string;
  sha256: string;
  stats: Record<string, number>;
  warnings: string[];
}
