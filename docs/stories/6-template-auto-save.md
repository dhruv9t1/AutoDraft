# Story 1.6: Template Auto-Save

Status: drafted

## Story

As a lawyer/paralegal/legal assistant,
I want my template to be automatically saved when I navigate away,
so that I don't lose my work if I accidentally close the form or switch to another template.

## Acceptance Criteria

1. When user creates a template and navigates away, template is automatically saved (AC10.1)
2. User cannot create multiple templates from the same document in one session (AC10.2)
3. If user attempts to create another template, previous template is saved first (AC10.3)

## Tasks / Subtasks

- [ ] Task 1: Implement Auto-Save on Navigation (AC: 1, 3)
  - [ ] Detect when user navigates away from template creation form
  - [ ] Auto-save template if it has been created but not yet saved
  - [ ] Handle auto-save errors gracefully
  - [ ] Show auto-save status to user (optional)
- [ ] Task 2: Implement Single Template Per Session Logic (AC: 2)
  - [ ] Track if template has been created in current session
  - [ ] Prevent creating multiple templates from same document
  - [ ] Show appropriate message if user attempts to create second template
- [ ] Task 3: Implement Save Before New Template (AC: 3)
  - [ ] Detect when user attempts to create new template
  - [ ] Save previous template first if exists
  - [ ] Then allow new template creation
  - [ ] Handle save errors before allowing new template

## Dev Notes

- Relevant architecture patterns and constraints
  - Auto-save patterns
  - Session state management
  - Lifecycle hooks for component unmounting
  - Debouncing for auto-save
- Source tree components to touch
  - `word-extension/src/taskpane/components/TemplateCreationForm.tsx` - Add auto-save logic
  - `word-extension/src/services/` - May need auto-save service
  - `word-extension/src/taskpane/components/App.tsx` - Track session state
- Testing standards summary
  - Unit tests for auto-save logic
  - Integration tests for save on navigation
  - Tests for single template per session
  - Tests for save before new template
  - Edge case tests (save failures, navigation interruptions)

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
  - Follow existing state management patterns
  - Use consistent session tracking
- Detected conflicts or variances (with rationale)
  - May need to establish session tracking mechanism
  - Auto-save may need debouncing to avoid excessive saves

### References

- PRD: `docs/Journey_1.1_Create_New_Template_PRD.md#FR010`
- Workflow: `docs/business-docs/01-project-overview.mdc#Journey-1.1` (Context)

## Workflow Dependencies

**Related Workflows:**
- Story 1.4 (Variable Confirmation and Template Creation) - Uses same save logic
- All stories - Auto-save affects all template creation flows

**Integration Points:**
- Auto-save must use same save logic as Story 1.4
- Session tracking must be consistent across journeys

## Impact Analysis

**Impact on Existing Systems:**
- Additional save operations (auto-save)
- Session state tracking
- May impact performance with frequent auto-saves

**Required Coordination:**
- Auto-save logic must be consistent with manual save (Story 1.4)
- Session tracking must be established

**Risk Considerations:**
- Auto-save may fail silently
- Performance impact of frequent auto-saves
- User may not be aware of auto-save status

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
