# Story 1.4: Variable Confirmation and Template Creation

Status: drafted

## Story

As a lawyer/paralegal/legal assistant,
I want to confirm detected variables and create my template,
so that I can save the template with all variables for future use.

## Acceptance Criteria

1. Checkbox is displayed below the "Auto Detect Variables" CTA with text: "I confirm the detected and custom added variables" (AC7.1)
2. Checkbox is unchecked by default (AC7.2)
3. User must check the checkbox to enable "Create Template" button (AC7.3, AC8.2)
4. "Create Template" button is displayed side by side with "Choose Existing Template" button (AC8.1)
5. "Create Template" button is disabled until user confirms variables (checkbox checked) (AC8.2)
6. On click, system saves template name, type, subtype, description, and all variables to database (AC8.3)
7. Variables are saved against the template name in database (AC8.4)
8. After successful save, system transitions to Journey 1.2 (Update Master Template) flow (AC8.5)
9. Database save operations must be transactional and atomic (NFR003)
10. Template creation must complete in less than 1 minute from start to finish (NFR001)

## Tasks / Subtasks

- [ ] Task 1: Implement Variable Confirmation Checkbox (AC: 1, 2, 3)
  - [ ] Add checkbox below "Auto Detect Variables" button
  - [ ] Set checkbox to unchecked by default
  - [ ] Implement checkbox change handler
  - [ ] Link checkbox state to "Create Template" button enable/disable
- [ ] Task 2: Implement Create Template Button (AC: 4, 5)
  - [ ] Add "Create Template" button side by side with "Choose Existing Template"
  - [ ] Implement button enable/disable logic based on checkbox
  - [ ] Add button styling according to mockup
- [ ] Task 3: Implement Template Save API Integration (AC: 6, 7, 9)
  - [ ] Create backend API endpoint for template creation (if not exists)
  - [ ] Send template metadata (name, type, subtype, description) to API
  - [ ] Send all variables to API
  - [ ] Implement transactional save (all or nothing)
  - [ ] Handle save errors gracefully
- [ ] Task 4: Implement Database Schema (AC: 7)
  - [ ] Verify existing database schema supports template storage
  - [ ] Create/update migrations if needed
  - [ ] Ensure variables are linked to template name
- [ ] Task 5: Implement Navigation to Journey 1.2 (AC: 8)
  - [ ] Navigate to Journey 1.2 after successful save
  - [ ] Pass template data to Journey 1.2
  - [ ] Handle navigation errors
- [ ] Task 6: Implement Performance Optimization (AC: 10)
  - [ ] Optimize database save operations
  - [ ] Ensure save completes within 1 minute
  - [ ] Add performance monitoring

## Dev Notes

- Relevant architecture patterns and constraints
  - Database transaction patterns
  - API endpoint design (RESTful)
  - State management for form and button states
  - Navigation patterns
- Source tree components to touch
  - `word-extension/src/taskpane/components/TemplateCreationForm.tsx` - Add checkbox and save button
  - `word-extension/src/services/` - Create template service for API calls
  - `backend/src/handlers.rs` - Create/update template creation endpoint
  - `backend/src/models.rs` - Add template model if needed
  - `backend/migrations/` - Create/update database migrations
- Testing standards summary
  - Unit tests for checkbox and button state management
  - Integration tests for template save API
  - Tests for database transaction atomicity
  - Tests for error handling
  - Performance tests for save operation (<1 minute)
  - Navigation tests for Journey 1.2 transition

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
  - Follow existing API endpoint patterns
  - Use existing database migration patterns
  - Maintain consistency with existing service structure
- Detected conflicts or variances (with rationale)
  - Need to verify database schema supports template storage
  - May need to create new API endpoint for template creation

### References

- PRD: `docs/Journey_1.1_Create_New_Template_PRD.md#FR007`, `docs/Journey_1.1_Create_New_Template_PRD.md#FR008`
- Workflow: `docs/business-docs/01-project-overview.mdc#Journey-1.1` (Steps 7, 8, 9)
- Database Schema: `backend/migrations/20250127000001_create_variables_table.sql`
- Backend Handler: `backend/src/handlers.rs`
- Backend Models: `backend/src/models.rs`

## Workflow Dependencies

**Related Workflows:**
- Journey 1.2 (Update Master Template) - Receives template data from this story
- Journey 1.3 (Fill Form with Variables) - Uses templates created here

**Integration Points:**
- Template data structure must match Journey 1.2 expectations
- Database schema must support template and variable storage
- Navigation must properly transition to Journey 1.2

## Impact Analysis

**Impact on Existing Systems:**
- New database records for templates and variables
- New API endpoint for template creation
- Database schema may need updates

**Required Coordination:**
- Database schema must be consistent with Journey 1.2 and 1.3
- Template data structure must match expectations
- API response format must be consistent

**Risk Considerations:**
- Database save operations reliability
- Transaction atomicity (all or nothing)
- Template naming conflicts (duplicate names)
- Performance with large variable sets

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
