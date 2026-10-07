from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

class CandidateEvidenceModel(ApiModel):
    code: str
    detail: str = ""
    weight: float | None = None

class Variable(ApiModel):
    id: str | None = None
    name: str
    original_text: str = Field(alias="originalText")
    position: int
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    current_value: str | None = Field(default=None, alias="currentValue")
    binding_id: str | None = Field(default=None, alias="bindingId")
    anchor_quality: Literal["exact","normalized","not_found"] | None = Field(default=None, alias="anchorQuality")
    source_occurrences: int | None = Field(default=None, alias="sourceOccurrences")
    grounded: bool | None = None
    candidate_id: str | None = Field(default=None, alias="candidateId")
    candidate_kind: str | None = Field(default=None, alias="candidateKind")
    candidate_group_id: str | None = Field(default=None, alias="candidateGroupId")
    variants: list[str] = Field(default_factory=list)
    repetition_count: int | None = Field(default=None, alias="repetitionCount")
    classification: Literal["replaceable_value","static_text","heading","label","boilerplate","ambiguous"] | None = None
    decision_source: Literal["rule","system1","qwen","lawyer","unreviewed"] | None = Field(default=None, alias="decisionSource")
    review_state: Literal["accepted","rejected","needs_review"] | None = Field(default=None, alias="reviewState")
    reason_codes: list[str] = Field(default_factory=list, alias="reasonCodes")
    candidate_evidence: list[CandidateEvidenceModel] = Field(default_factory=list, alias="candidateEvidence")
    decision_record_id: str | None = Field(default=None, alias="decisionRecordId")


class OrganizationAIPolicyUpdateRequest(ApiModel):
    external_system1_enabled: bool = Field(default=False, alias="externalSystem1Enabled")
    provider: Literal["off","jev"] = "off"
    provider_model: str = Field(default="", alias="providerModel", max_length=200)
    consent_note: str = Field(default="", alias="consentNote", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)

class CandidateLawyerReviewRequest(ApiModel):
    disposition: Literal["accepted","rejected"]
    reason: str = Field(default="", max_length=2000)

class VariableBlock(ApiModel):
    type: Literal["atomic", "parent"]
    variable: Variable | None = None
    label: str | None = None
    children: list[Variable] | None = None

class WrappingPlanEntry(ApiModel):
    variable_index: int = Field(alias="variableIndex")
    search_text: str = Field(alias="searchText")
    use_wildcards: bool = Field(alias="useWildcards")
    insert_braces: bool = Field(alias="insertBraces")
    absorbed_by: int | None = Field(default=None, alias="absorbedBy")

class VariableIdentificationRequest(ApiModel):
    document_content: str = Field(alias="documentContent")
    template_id: str | None = Field(default=None, alias="templateId")
    template_name: str | None = Field(default=None, alias="templateName")
    known_variables: list[Variable] | None = Field(default=None, alias="knownVariables")
    segments: list[dict] | None = None

class VariableIdentificationResponse(ApiModel):
    variables: list[Variable]
    variable_blocks: list[VariableBlock] | None = Field(default=None, alias="variableBlocks")
    identification_percentage: float = Field(alias="identificationPercentage")
    status: Literal["completed", "completed_with_review", "no_fields", "unavailable", "failed"]
    message: str | None = None
    wrapping_plan: list[WrappingPlanEntry] | None = Field(default=None, alias="wrappingPlan")
    identification_mode: Literal["legal","general"] | None = Field(default=None, alias="identificationMode")
    coverage_warnings: list[str] = Field(default_factory=list, alias="coverageWarnings")

class DocxLegacyFontFinding(ApiModel):
    font_name: str = Field(alias="fontName")
    run_count: int = Field(alias="runCount")
    inherited_only: bool = Field(default=False, alias="inheritedOnly")

class DocxDiagnosticsResponse(ApiModel):
    paragraph_count: int = Field(alias="paragraphCount")
    story_counts: dict[str, int] = Field(default_factory=dict, alias="storyCounts")
    legacy_fonts: list[DocxLegacyFontFinding] = Field(default_factory=list, alias="legacyFonts")
    warnings: list[str] = Field(default_factory=list)

class BoilerplateCreateRequest(ApiModel):
    value: str
    label: str = ""
    kind: str = "firm_value"

class BoilerplateEntry(ApiModel):
    id: str
    value: str
    label: str = ""
    kind: str = "firm_value"
    active: bool = True

class CreateTemplateRequest(ApiModel):
    name: str
    type: str = ""
    subtype: str = ""
    description: str = ""
    variables: list[Variable]

class UpdateTemplateContentRequest(ApiModel):
    body_ooxml: str = Field(default="", alias="bodyOoxml")
    is_compressed: bool = Field(default=False, alias="isCompressed")
    docx_base64: str | None = Field(default=None, alias="docxBase64")
    snapshot_kind: str | None = Field(default=None, alias="snapshotKind")

class AddTemplateVariableRequest(ApiModel):
    name: str
    original_text: str = Field(alias="originalText")
    position: int
    confidence_score: float | None = Field(default=None, alias="confidenceScore")
    binding_id: str | None = Field(default=None, alias="bindingId")

class UpdateVariableRequest(ApiModel):
    name: str
    current_value: str | None = Field(default=None, alias="currentValue")

class VariableValueEntry(ApiModel):
    variable_name: str = Field(alias="variableName")
    current_value: str = Field(alias="currentValue")

class SaveVariableValuesRequest(ApiModel):
    values: list[VariableValueEntry]


class StartDocumentChunkedRequest(ApiModel):
    total_chunks: int = Field(alias="totalChunks")
    template_id: str | None = Field(default=None, alias="templateId")
    template_name: str | None = Field(default=None, alias="templateName")

class UploadDocumentChunkRequest(ApiModel):
    session_id: str = Field(alias="sessionId")
    chunk_index: int = Field(alias="chunkIndex")
    chunk_content: str = Field(alias="chunkContent")

class FinalizeDocumentChunkedRequest(ApiModel):
    session_id: str = Field(alias="sessionId")

class StartOoxmlChunkedUploadRequest(ApiModel):
    total_chunks: int = Field(alias="totalChunks")
    total_size: int = Field(alias="totalSize")

class UploadOoxmlChunkRequest(ApiModel):
    session_id: str = Field(alias="sessionId")
    chunk_index: int = Field(alias="chunkIndex")
    chunk_data: str = Field(alias="chunkData")
    total_chunks: int = Field(alias="totalChunks")

class FinalizeOoxmlChunkedUploadRequest(ApiModel):
    session_id: str = Field(alias="sessionId")

class SummaryRequest(ApiModel):
    document_content: str = Field(alias="documentContent")
    language: str | None = None

class RiskAssessmentRequest(ApiModel):
    document_content: str = Field(alias="documentContent")
    document_type: str | None = Field(default=None, alias="documentType")

class DeadlineRequest(ApiModel):
    document_content: str = Field(alias="documentContent")

class VerificationRequest(ApiModel):
 document_content:str=Field(alias="documentContent");variables:list[Variable];current_values:dict[str,str]=Field(default_factory=dict,alias="currentValues");legal_mode:bool=Field(default=True,alias="legalMode")
class VerificationIssue(ApiModel):
 severity:Literal["blocker","warning","info"];code:str;message:str;variable_name:str|None=Field(default=None,alias="variableName");evidence:str|None=None
class VerificationResponse(ApiModel):
 status:Literal["pass","review","block"];issues:list[VerificationIssue];blockers:int;warnings:int;checked_variables:int=Field(alias="checkedVariables")
class DraftingMessage(ApiModel): role:Literal["user","assistant"];content:str
class RetrievedAuthority(ApiModel):
 title:str;citation:str="";court:str="";date:str="";source_url:str=Field(default="",alias="sourceUrl");excerpt:str=""
class DraftingChatRequest(ApiModel):
 message:str;conversation:list[DraftingMessage]=Field(default_factory=list);matter_type:str=Field(default="",alias="matterType");facts:dict[str,str]=Field(default_factory=dict);research_opt_in:bool=Field(default=False,alias="researchOptIn");retrieved_authorities:list[RetrievedAuthority]=Field(default_factory=list,alias="retrievedAuthorities");mode:Literal["answer","complete_document"]="answer"
class IntakeGenerateRequest(ApiModel): matter_type:str=Field(alias="matterType");known_facts:dict[str,str]=Field(default_factory=dict,alias="knownFacts")
class IntakeQuestion(ApiModel):
    id: str
    label: str
    type: Literal[
        "text", "textarea", "date", "number", "currency", "email", "phone",
        "select", "boolean", "address", "person", "multi_select", "file"
    ] = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)
    maps_to: str = Field(default="", alias="mapsTo")
    help_text: str = Field(default="", alias="helpText")
    approved: bool = True
    section_id: str | None = Field(default=None, alias="sectionId")
    position: int = 0
    display_rule: dict | None = Field(default=None, alias="displayRule")
    validation: dict = Field(default_factory=dict)
class IntakeGenerateResponse(ApiModel): title:str;matter_type:str=Field(alias="matterType");questions:list[IntakeQuestion]
class IntakeShareRequest(ApiModel): title:str;matter_type:str=Field(alias="matterType");questions:list[IntakeQuestion];template_id:str|None=Field(default=None,alias="templateId")
class IntakeSubmission(ApiModel): answers:dict[str,Any]


class MatterCreateRequest(ApiModel):
    title: str
    matter_type: str = Field(default="", alias="matterType")
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    stage_id: str | None = Field(default=None, alias="stageId")
    reference_code: str = Field(default="", alias="referenceCode")

class MatterUpdateRequest(ApiModel):
    title: str | None = None
    matter_type: str | None = Field(default=None, alias="matterType")
    status: Literal["open","pending","closed","archived"] | None = None
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    stage_id: str | None = Field(default=None, alias="stageId")
    reference_code: str | None = Field(default=None, alias="referenceCode")
class TemplateUpdateRequest(ApiModel):
 name:str|None=None;type:str|None=None;subtype:str|None=None;description:str|None=None
class MatterFactRequest(ApiModel):
 field:str;fact:str;source:str="user";status:str="client_claim"
class MatterAuthorityRequest(ApiModel):
 title:str;citation:str="";source_url:str=Field(default="",alias="sourceUrl")

class MatterAuthorityVerificationRequest(ApiModel):
 status: Literal["lawyer_verified","rejected"]
 note: str = ""
 evidence: dict[str, Any] = Field(default_factory=dict)

# ═══════════════════════════════════════════════════════════════════
# vNext remaining architecture contracts
# ═══════════════════════════════════════════════════════════════════

class ExistingControl(ApiModel):
    tag: str
    title: str = ""
    text: str = ""

class DocumentSource(ApiModel):
    story: Literal["body", "table", "header", "footer"]
    paragraph_index: int | None = Field(default=None, alias="paragraphIndex")
    table_index: int | None = Field(default=None, alias="tableIndex")
    row_index: int | None = Field(default=None, alias="rowIndex")
    cell_index: int | None = Field(default=None, alias="cellIndex")
    section_index: int | None = Field(default=None, alias="sectionIndex")
    header_footer_kind: str | None = Field(default=None, alias="headerFooterKind")

class DocumentSegment(ApiModel):
    segment_id: str = Field(alias="segmentId")
    source: DocumentSource
    text: str
    normalized_text: str = Field(alias="normalizedText")
    existing_controls: list[ExistingControl] = Field(default_factory=list, alias="existingControls")
    global_start: int | None = Field(default=None, alias="globalStart")
    global_end: int | None = Field(default=None, alias="globalEnd")

class DocumentStructure(ApiModel):
    text: str
    normalized_text: str = Field(alias="normalizedText")
    segments: list[DocumentSegment] = Field(default_factory=list)

# Extend extraction request with canonical structural source metadata without
# breaking existing clients that send only documentContent.
VariableIdentificationRequest.model_fields["document_content"]

class BindingEndpoint(ApiModel):
    segment_id: str = Field(alias="segmentId")
    offset: int

class BindingSourceRange(ApiModel):
    start: BindingEndpoint
    end: BindingEndpoint

class BindingOperation(ApiModel):
    operation_id: str = Field(alias="operationId")
    binding_id: str = Field(alias="bindingId")
    field_id: str | None = Field(default=None, alias="fieldId")
    semantic_key: str = Field(default="", alias="semanticKey")
    display_label: str = Field(default="", alias="displayLabel")
    expected_text: str = Field(alias="expectedText")
    occurrence_id: str = Field(alias="occurrenceId")
    source: BindingSourceRange

class BindingConflict(ApiModel):
    code: Literal["not_found","ambiguous","overlap","existing_control","duplicate_binding","unsupported_segment"]
    message: str
    binding_id: str | None = Field(default=None, alias="bindingId")
    blocking: bool = True

class BindingPlan(ApiModel):
    operations: list[BindingOperation] = Field(default_factory=list)
    conflicts: list[BindingConflict] = Field(default_factory=list)
    can_commit: bool = Field(alias="canCommit")

class TemplateSnapshotRequest(ApiModel):
    docx_base64: str = Field(alias="docxBase64")
    body_ooxml: str | None = Field(default=None, alias="bodyOoxml")
    metadata: dict[str, Any] = Field(default_factory=dict)

class MatterDocumentCreateRequest(ApiModel):
    name: str
    docx_base64: str = Field(alias="docxBase64")
    mime_type: str = Field(default="application/vnd.openxmlformats-officedocument.wordprocessingml.document", alias="mimeType")
    source: str = "captured"
    metadata: dict[str, Any] = Field(default_factory=dict)

class MatterDocumentUpdateRequest(ApiModel):
    name: str | None = None
    archived: bool | None = None

class IntakeDisplayRule(ApiModel):
    question_id: str = Field(alias="questionId")
    operator: Literal["equals","not_equals","exists","not_exists","contains"] = "equals"
    value: Any | None = None

class IntakeValidation(ApiModel):
    min_length: int | None = Field(default=None, alias="minLength")
    max_length: int | None = Field(default=None, alias="maxLength")
    min_value: float | None = Field(default=None, alias="minValue")
    max_value: float | None = Field(default=None, alias="maxValue")
    pattern: str | None = None
    allowed_extensions: list[str] = Field(default_factory=list, alias="allowedExtensions")

class IntakeSection(ApiModel):
    id: str
    title: str
    description: str = ""
    position: int = 0

class QuestionnaireSaveRequest(ApiModel):
    id: str | None = None
    title: str
    matter_type: str = Field(default="", alias="matterType")
    sections: list[IntakeSection] = Field(default_factory=list)
    questions: list[IntakeQuestion]

class IntakePublishRequest(ApiModel):
    questionnaire_id: str = Field(alias="questionnaireId")
    matter_id: str | None = Field(default=None, alias="matterId")
    expires_in_days: int = Field(default=7, alias="expiresInDays", ge=1, le=90)

class FactConflictResolutionRequest(ApiModel):
    fact_id: str | None = Field(default=None, alias="factId")
    value: str | None = None
    dismiss: bool = False

class DerivedFactRuleRequest(ApiModel):
    fact_key: str = Field(alias="factKey")
    label: str
    value_type: str = Field(default="text", alias="valueType")
    expression: dict[str, Any]
    enabled: bool = True

class MissingFact(ApiModel):
    key: str = ""
    label: str = ""
    question: str = ""
    required: bool = True

class DraftResult(ApiModel):
    answer: str = ""
    draft: str = ""
    sections: list[str] = Field(default_factory=list)
    missing_information: list[MissingFact] = Field(default_factory=list, alias="missingInformation")
    questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    authorities_used: list[dict[str, Any]] = Field(default_factory=list, alias="authoritiesUsed")
    fact_ledger: list[dict[str, Any]] = Field(default_factory=list, alias="factLedger")
    citation_verification: dict[str, Any] = Field(default_factory=dict, alias="citationVerification")
    review_findings: list[dict[str, Any]] = Field(default_factory=list, alias="reviewFindings")
    qa_issues: list[dict[str, Any]] = Field(default_factory=list, alias="qaIssues")
    plan: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# Clio-inspired canonical legal data contracts
# ═══════════════════════════════════════════════════════════════════

ContactType = Literal["person", "company"]
FieldScope = Literal["matter", "contact"]
FieldValueType = Literal[
    "text","long_text","integer","decimal","currency","date","datetime","boolean",
    "choice","multi_choice","email","phone","address","contact_reference","matter_reference",
    "document_reference","json",
]

class ContactCreateRequest(ApiModel):
    contact_type: ContactType = Field(default="person", alias="contactType")
    display_name: str = Field(alias="displayName")
    first_name: str = Field(default="", alias="firstName")
    middle_name: str = Field(default="", alias="middleName")
    last_name: str = Field(default="", alias="lastName")
    company_name: str = Field(default="", alias="companyName")
    email: str = ""
    phone: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

class ContactUpdateRequest(ApiModel):
    contact_type: ContactType | None = Field(default=None, alias="contactType")
    display_name: str | None = Field(default=None, alias="displayName")
    first_name: str | None = Field(default=None, alias="firstName")
    middle_name: str | None = Field(default=None, alias="middleName")
    last_name: str | None = Field(default=None, alias="lastName")
    company_name: str | None = Field(default=None, alias="companyName")
    email: str | None = None
    phone: str | None = None
    metadata: dict[str, Any] | None = None
    archived: bool | None = None

class MatterParticipantCreateRequest(ApiModel):
    contact_id: str = Field(alias="contactId")
    role_key: str = Field(alias="roleKey")
    display_role: str = Field(alias="displayRole")
    is_client: bool = Field(default=False, alias="isClient")
    is_primary: bool = Field(default=False, alias="isPrimary")
    represented_by_firm: bool = Field(default=False, alias="representedByFirm")
    position: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

class MatterParticipantUpdateRequest(ApiModel):
    role_key: str | None = Field(default=None, alias="roleKey")
    display_role: str | None = Field(default=None, alias="displayRole")
    is_client: bool | None = Field(default=None, alias="isClient")
    is_primary: bool | None = Field(default=None, alias="isPrimary")
    represented_by_firm: bool | None = Field(default=None, alias="representedByFirm")
    position: int | None = None
    metadata: dict[str, Any] | None = None

class PracticeAreaCreateRequest(ApiModel):
    key: str
    name: str
    description: str = ""
    position: int = 0
    active: bool = True

class PracticeAreaUpdateRequest(ApiModel):
    name: str | None = None
    description: str | None = None
    position: int | None = None
    active: bool | None = None

class MatterStageCreateRequest(ApiModel):
    key: str
    name: str
    practice_area_id: str = Field(alias="practiceAreaId")
    description: str = ""
    position: int = 0
    active: bool = True

class MatterStageUpdateRequest(ApiModel):
    name: str | None = None
    description: str | None = None
    position: int | None = None
    active: bool | None = None

class FieldGroupCreateRequest(ApiModel):
    key: str
    label: str
    entity_scope: FieldScope = Field(default="matter", alias="entityScope")
    role_key: str | None = Field(default=None, alias="roleKey")
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    position: int = 0

class FieldDefinitionCreateRequest(ApiModel):
    semantic_key: str = Field(alias="semanticKey")
    display_label: str = Field(alias="displayLabel")
    description: str = ""
    entity_scope: FieldScope = Field(default="matter", alias="entityScope")
    value_type: FieldValueType = Field(default="text", alias="valueType")
    repeatable: bool = False
    required: bool = False
    validation: dict[str, Any] = Field(default_factory=dict)
    formatting: dict[str, Any] = Field(default_factory=dict)
    options: list[Any] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    group_id: str | None = Field(default=None, alias="groupId")
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    matter_type: str = Field(default="", alias="matterType")
    position: int = 0
    active: bool = True

class FieldDefinitionUpdateRequest(ApiModel):
    display_label: str | None = Field(default=None, alias="displayLabel")
    description: str | None = None
    value_type: FieldValueType | None = Field(default=None, alias="valueType")
    repeatable: bool | None = None
    required: bool | None = None
    validation: dict[str, Any] | None = None
    formatting: dict[str, Any] | None = None
    options: list[Any] | None = None
    aliases: list[str] | None = None
    group_id: str | None = Field(default=None, alias="groupId")
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    matter_type: str | None = Field(default=None, alias="matterType")
    position: int | None = None
    active: bool | None = None

class FieldValueUpsertRequest(ApiModel):
    value: Any
    source: str = "user"
    status: str = "confirmed"
    provenance: dict[str, Any] = Field(default_factory=dict)

class DocumentSetItemInput(ApiModel):
    template_id: str = Field(alias="templateId")
    label: str = ""
    position: int = 0
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

class DocumentSetCreateRequest(ApiModel):
    name: str
    description: str = ""
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    matter_type: str = Field(default="", alias="matterType")
    items: list[DocumentSetItemInput] = Field(default_factory=list)

class DocumentSetUpdateRequest(ApiModel):
    name: str | None = None
    description: str | None = None
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    matter_type: str | None = Field(default=None, alias="matterType")
    items: list[DocumentSetItemInput] | None = None

class GenerationRunCreateRequest(ApiModel):
    matter_id: str = Field(alias="matterId")
    document_set_version_id: str = Field(alias="documentSetVersionId")
    selected_items: list[str] = Field(default_factory=list, alias="selectedItems")

class GenerationRunUpdateRequest(ApiModel):
    status: Literal["selection","population","review","completed","failed"]
    metadata: dict[str, Any] = Field(default_factory=dict)

# ═══════════════════════════════════════════════════════════════════
# Gavel-inspired workflow/document automation contracts
# ═══════════════════════════════════════════════════════════════════

WorkflowAudience = Literal["internal", "client", "both"]

class WorkflowCreateRequest(ApiModel):
    name: str
    description: str = ""
    audience: WorkflowAudience = "internal"
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    matter_type: str = Field(default="", alias="matterType")
    definition: dict[str, Any] = Field(default_factory=lambda: {"pages": [], "calculations": []})

class WorkflowUpdateRequest(ApiModel):
    name: str | None = None
    description: str | None = None
    audience: WorkflowAudience | None = None
    practice_area_id: str | None = Field(default=None, alias="practiceAreaId")
    matter_type: str | None = Field(default=None, alias="matterType")
    definition: dict[str, Any] | None = None

class WorkflowSessionCreateRequest(ApiModel):
    matter_id: str | None = Field(default=None, alias="matterId")
    expires_in_days: int = Field(default=30, alias="expiresInDays", ge=1, le=180)
    metadata: dict[str, Any] = Field(default_factory=dict)

class WorkflowSessionUpdateRequest(ApiModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    current_page: str | None = Field(default=None, alias="currentPage")
    metadata: dict[str, Any] = Field(default_factory=dict)

class TemplateAutomationSaveRequest(ApiModel):
    blueprint: dict[str, Any] = Field(default_factory=lambda: {"bindings": [], "conditions": [], "repeaters": []})

class HeadlessGenerationRequest(ApiModel):
    matter_id: str | None = Field(default=None, alias="matterId")
    template_id: str | None = Field(default=None, alias="templateId")
    template_version: int | None = Field(default=None, alias="templateVersion", ge=1)
    document_set_version_id: str | None = Field(default=None, alias="documentSetVersionId")
    workflow_session_id: str | None = Field(default=None, alias="workflowSessionId")
    generation_run_id: str | None = Field(default=None, alias="generationRunId")
    data_overrides: dict[str, Any] = Field(default_factory=dict, alias="dataOverrides")
    override_reason: str | None = Field(default=None, alias="overrideReason", max_length=1000)
    save_to_matter: bool = Field(default=True, alias="saveToMatter")
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey", min_length=8, max_length=200)
