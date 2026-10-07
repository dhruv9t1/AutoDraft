# Story 1.3: Variable Processing and Display

Status: in-progress

## Story

As a lawyer/paralegal/legal assistant,
I want detected variables to be linked to stable Word content controls,
so that I can see, edit, and fill fields without replacing source text with marker tokens.

## Acceptance Criteria

1. Detected variables are linked with Word content controls while preserving their source text (AC6.1)
2. Content controls use immutable binding IDs; display labels may change without changing identity (AC6.2)
3. User can manually add a missed field through the add-in and link it to the document (AC6.3)
4. No `[[...]]` or `{...}` marker-token convention is required for the current content-control workflow (Impact Analysis)
5. Both AI-identified and manually added variables are saved with the template (AC6.4)

## Tasks / Subtasks

- [x] Task 1: Implement Variable Formatting Logic (AC: 1, 2)
  - [x] Build a structural binding plan for detected variables
  - [x] Preserve original document text and insert Word content controls around grounded spans
  - [x] Ensure variable names are properly escaped/sanitized (Already implemented)
- [x] Task 2: Implement Document Variable Replacement (AC: 2)
  - [x] Use Office Add-in API to replace text in Word document (Already implemented)
  - [x] Handle multiple occurrences of same variable (Already implemented)
  - [x] Preserve document formatting where possible (Already implemented)
- [x] Task 3: Enable Manual Variable Editing (AC: 3)
  - [x] Allow the user to add missed variables through the add-in and link them to Word
  - [x] Extract all variables from document (both AI-identified and manually added) before saving
  - [x] Sync manual edits with variable list when creating template
- [x] Task 4: Implement Variable Format Validation (AC: 4)
  - [x] Validate immutable binding identity and expected source text
  - [x] Ensure binding consistency across the document
  - [x] Handle overlapping and repeated source spans without nested-control corruption
- [x] Task 5: Extract and Save All Variables to Database (AC: 5)
  - [x] Persist all approved variables and binding metadata before template creation
  - [x] Merge AI-identified variables with manually added variables
  - [x] Save all variables (both identified and manually edited) to database

## Dev Notes

- Relevant architecture patterns and constraints
  - Office Add-in API for document manipulation
  - Immutable content-control binding patterns
  - Binding identity and source-grounding validation
- Source tree components to touch
  - `word-extension/src/services/word/documentStructure.ts` - Structural Word extraction
  - `word-extension/src/taskpane/components/TemplateCreationForm.tsx` - Add variable editing UI
  - `word-extension/src/services/word/bindingPlanner.ts` - Pure binding-plan construction
- Testing standards summary
  - Unit tests for variable formatting logic
  - Integration tests for content-control binding and filling
  - Tests for manual variable editing
  - Tests for variable format validation
  - Edge case tests (special characters, repeated values, overlaps, story boundaries)

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
  - Follow existing document manipulation patterns
  - Use consistent variable naming conventions
  - Maintain immutable binding identity across detection, wrapping, and filling
- Detected conflicts or variances (with rationale)
  - Journey 1.2 and 1.3 must consume the same immutable binding IDs
  - Content-control insertion must preserve document formatting

### References

- PRD: `docs/Journey_1.1_Create_New_Template_PRD.md#FR006`
- Workflow: `docs/business-docs/01-project-overview.mdc#Journey-1.1` (Step 6)
- Document Extraction: `word-extension/src/services/documentExtraction.ts`
- Variable Service: `word-extension/src/services/aiVariableService.ts`

## Workflow Dependencies

**Related Workflows:**
- Journey 1.2 (Update Master Template) - Uses the same content-control bindings
- Journey 1.3 (Fill Form with Variables) - Fills values through those bindings

**Integration Points:**
- Binding identity must be stable across Journey 1.2 and 1.3
- Manual edits must sync with variable list (Story 1.2)
- Variables will be saved in Story 1.4

## Impact Analysis

**Impact on Existing Systems:**
- Document structure is modified by inserting content controls around grounded source text
- Binding identity must be consistent across all journeys

**Required Coordination:**
- Immutable binding IDs must be consistent with Journey 1.2 and 1.3
- Manual edits must be tracked and synced

**Risk Considerations:**
- Content-control insertion must preserve formatting and avoid unsupported story crossings
- Manual additions may fail grounding and must not block unrelated safe bindings
- Repeated values and overlap resolution require deterministic binding-plan behavior

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

Auto (Cursor AI Agent)

### Debug Log References

### Completion Notes List

1. **Binding workflow current state**: Detected variables keep their source text and are linked to Word content controls using immutable binding IDs. No marker-token rewrite is required.

2. **Structural grounding**: `extractDocumentStructure()` supplies the ordered structural text used by both backend detection positions and the frontend binding planner. The planner resolves occurrences before Word mutation.

3. **Template creation**: `TemplateCreationForm.tsx` commits the binding plan, reports skipped/ungroundable variables, and then persists the approved variable set.

4. **Manual additions**: The add-in can create a variable from selected/source text and run it through the same structural binding plan. If it cannot be grounded, the add operation fails without preventing unrelated variables from being wrapped.

### File List

**Modified Files:**
- `docs/stories/3-variable-processing-and-display.md` - Updated story format and marked tasks complete
- `word-extension/src/services/word/documentStructure.ts` - Structural document extraction
- `word-extension/src/services/word/bindingPlanner.ts` - Immutable binding-plan construction
- `word-extension/src/taskpane/components/TemplateCreationForm.tsx` - Binding-plan commit and template persistence
