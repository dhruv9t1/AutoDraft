# Story 1.2: Auto Detect Variables Feature

Status: drafted

## Story

As a lawyer/paralegal/legal assistant,
I want to automatically detect variables from my document using AI,
so that I can quickly identify all variables without manually searching through the document.

## Acceptance Criteria

1. "Auto Detect Variables" button is displayed below the template metadata fields (AC3.1)
2. Button is disabled until user enters template details (name, type, subtype) (AC3.2)
3. On click, the system calls AI LLM service to identify variables (AC3.3)
4. Document content is passed to the AI service (AC3.4)
5. Loading indicator is shown during AI processing (AC3.5)
6. AI processes the document content and identifies variables (AC4.1)
7. System validates that AI identified at least 80% of variables (AC4.2)
8. If AI detects 0% or less than 80% variables, system prompts user: "Ask user to define it manually" (AC4.3)
9. If document is empty when "Auto Detect Variables" is clicked, system prompts: "Ask user to upload a document" (AC4.4)
10. If document contains no variables (plain text only), system prompts: "Ask user to define it manually" (AC4.5)
11. After AI processing, system displays message: "We have identified X number of variables in the document" (AC5.1)
12. Variables are displayed as a list (not inline in document) (AC5.2)
13. User can view all detected variables in the list (AC5.3)
14. AI variable detection must complete within 10 seconds for documents up to 5MB (NFR001)
15. UI must remain responsive during AI processing (NFR001)
16. System must handle AI service failures gracefully (fallback to manual entry) (NFR003)

## Tasks / Subtasks

- [ ] Task 1: Implement Auto Detect Variables Button (AC: 1, 2)
  - [ ] Add "Auto Detect Variables" button below template metadata fields
  - [ ] Implement button enable/disable logic based on form validation
  - [ ] Add button styling according to mockup
- [ ] Task 2: Implement Document Content Extraction (AC: 4)
  - [ ] Extract document content from Word document using Office Add-in API
  - [ ] Validate document is not empty
  - [ ] Handle document extraction errors
- [ ] Task 3: Integrate AI LLM Service Call (AC: 3, 6)
  - [ ] Call existing AI service endpoint (`backend/src/ollama.rs`)
  - [ ] Pass document content to AI service
  - [ ] Handle API request/response
  - [ ] Implement error handling for API failures
- [ ] Task 4: Implement Loading Indicator (AC: 5, 15)
  - [ ] Show loading indicator during AI processing
  - [ ] Ensure UI remains responsive
  - [ ] Add loading state management
- [ ] Task 5: Implement Variable Detection Validation (AC: 7, 8, 9, 10)
  - [ ] Validate AI detected at least 80% of variables
  - [ ] Handle empty document case
  - [ ] Handle no variables detected case
  - [ ] Show appropriate error messages
- [ ] Task 6: Display Variable Detection Results (AC: 11, 12, 13)
  - [ ] Display message with variable count
  - [ ] Display variables as a list
  - [ ] Implement variable list component
  - [ ] Ensure list is scrollable for large variable sets
- [ ] Task 7: Implement Error Handling and Fallback (AC: 16)
  - [ ] Handle AI service failures gracefully
  - [ ] Provide fallback to manual entry
  - [ ] Show clear error messages
  - [ ] Allow retry mechanism

## Dev Notes

- Relevant architecture patterns and constraints
  - Existing AI service integration (`backend/src/ollama.rs`)
  - Document extraction service (`word-extension/src/services/documentExtraction.ts`)
  - Existing variable service (`word-extension/src/services/aiVariableService.ts`)
  - Error handling patterns
- Source tree components to touch
  - `word-extension/src/taskpane/components/TemplateCreationForm.tsx` - Add button and variable list
  - `word-extension/src/services/documentExtraction.ts` - Use existing document extraction
  - `word-extension/src/services/aiVariableService.ts` - Use existing AI variable service
  - `backend/src/handlers.rs` - Verify existing endpoint supports requirements
  - `backend/src/ollama.rs` - Verify AI service meets 80% threshold requirement
- Testing standards summary
  - Unit tests for button enable/disable logic
  - Integration tests for AI service calls
  - Tests for variable detection validation (80% threshold)
  - Tests for error handling scenarios
  - Performance tests for AI processing time (<10 seconds)
  - UI tests for loading indicators

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
  - Use existing services for document extraction and AI calls
  - Follow existing error handling patterns
  - Maintain consistency with existing API structure
- Detected conflicts or variances (with rationale)
  - Need to verify AI service can meet 80% detection threshold
  - May need to enhance error handling in existing services

### References

- PRD: `docs/Journey_1.1_Create_New_Template_PRD.md#FR003`, `docs/Journey_1.1_Create_New_Template_PRD.md#FR004`, `docs/Journey_1.1_Create_New_Template_PRD.md#FR005`
- Existing AI Service: `backend/src/ollama.rs`
- Existing Variable Service: `word-extension/src/services/aiVariableService.ts`
- Document Extraction: `word-extension/src/services/documentExtraction.ts`
- Backend Handler: `backend/src/handlers.rs`

## Workflow Dependencies

**Related Workflows:**
- Journey 1.2 (Update Master Template) - Uses same AI variable detection
- Journey 1.3 (Fill Form with Variables) - Uses variables detected here

**Integration Points:**
- AI service must support 80% detection threshold
- Variable list will be used in Story 1.3 for processing
- Detected variables will be saved in Story 1.4

## Impact Analysis

**Impact on Existing Systems:**
- Increased usage of AI service (may need performance optimization)
- Document extraction service usage
- Backend API endpoint usage

**Required Coordination:**
- AI service must meet 80% detection accuracy requirement
- Error handling must be consistent across journeys
- Variable format must be consistent ([variable name])

**Risk Considerations:**
- AI variable detection accuracy (80% threshold may not be achievable in all cases)
- AI service availability and response time
- Document size limitations (5MB)

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
