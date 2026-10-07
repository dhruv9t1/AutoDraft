# Story 1.5: Choose Existing Template Navigation

Status: drafted

## Story

As a lawyer/paralegal/legal assistant,
I want to choose an existing template at any time during template creation,
so that I can switch to filling a form with variables from an existing template instead of creating a new one.

## Acceptance Criteria

1. "Choose Existing Template" button is displayed side by side with "Create Template" button (AC9.1)
2. Button is available at any time (not dependent on variable detection) (AC9.2)
3. On click, system navigates to Journey 1.3 (Fill Form with Variables) (AC9.3)

## Tasks / Subtasks

- [ ] Task 1: Implement Choose Existing Template Button (AC: 1, 2)
  - [ ] Add "Choose Existing Template" button side by side with "Create Template"
  - [ ] Ensure button is always enabled (not dependent on form state)
  - [ ] Add button styling according to mockup
- [ ] Task 2: Implement Navigation to Journey 1.3 (AC: 3)
  - [ ] Create navigation handler for Journey 1.3
  - [ ] Pass any relevant context/data to Journey 1.3
  - [ ] Handle navigation errors
  - [ ] Ensure smooth transition

## Dev Notes

- Relevant architecture patterns and constraints
  - Navigation patterns in Office Add-in
  - State management for navigation
  - Component routing
- Source tree components to touch
  - `word-extension/src/taskpane/components/TemplateCreationForm.tsx` - Add navigation button
  - `word-extension/src/taskpane/components/App.tsx` - Handle navigation routing
  - `word-extension/src/taskpane/components/` - Journey 1.3 component (if exists)
- Testing standards summary
  - Unit tests for button rendering and state
  - Integration tests for navigation
  - Tests for navigation error handling
  - UI tests for button availability

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
  - Follow existing navigation patterns
  - Maintain consistency with component routing
- Detected conflicts or variances (with rationale)
  - Journey 1.3 component may need to be created
  - Navigation pattern may need to be established

### References

- PRD: `docs/Journey_1.1_Create_New_Template_PRD.md#FR009`
- Workflow: `docs/business-docs/01-project-overview.mdc#Journey-1.1` (Step 10)
- Journey 1.3: `docs/business-docs/01-project-overview.mdc#Journey-1.3`

## Workflow Dependencies

**Related Workflows:**
- Journey 1.3 (Fill Form with Variables) - Destination of navigation

**Integration Points:**
- Navigation must properly transition to Journey 1.3
- Any context/data must be passed correctly
- Journey 1.3 must be able to receive navigation from this story

## Impact Analysis

**Impact on Existing Systems:**
- New navigation path to Journey 1.3
- May require Journey 1.3 component creation

**Required Coordination:**
- Journey 1.3 must be ready to receive navigation
- Navigation context must be properly defined

**Risk Considerations:**
- Journey 1.3 may not be implemented yet (dependency)
- Navigation errors if Journey 1.3 is unavailable

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
