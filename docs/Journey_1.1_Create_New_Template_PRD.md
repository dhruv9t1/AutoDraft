# Product Requirements Document - Journey 1.1: Create New Template

**Author:** My Coat Team  
**Date:** 2025-01-27  
**Project:** My Coat - Word Add-in for Legal Document Templates  
**Story Complexity:** Level 1 (Small feature: 1-10 stories)  
**Expected Story Count:** 5-8 stories

---

## 1. Goals and Background

### 1.1 Business Goals
- **Primary Goal:** Decrease the time taken to draft a template
- **Success Metric:** User should be able to draft a template in less than 1 minute
- **Target Users:** Lawyers, paralegals, legal assistants
- **Business Problem:** Drafting documents is time-consuming for lawyers. This system will help lawyers draft documents faster, more efficiently, accurately, consistently, easily, and quickly.

### 1.2 Product Context
My Coat is a Word Add-in that enables lawyers to create and manage legal document templates with dynamic variables. The add-in appears as a React app on the left side of the Word document, providing a seamless template creation and management experience.

### 1.3 Feature Overview
Journey 1.1 enables users to create a new template from their current Word document. The feature guides users through:
1. Entering template metadata (name, type, subtype, description)
2. Auto-detecting variables from the document using AI
3. Confirming detected variables
4. Creating and saving the template

---

## 2. Functional Requirements

### FR001: Template Creation Form
**Priority:** High  
**Description:** User must be able to access the "Create a new template" feature with the label "Create a new template" and description "Turn your current document into a standard template."

**Acceptance Criteria:**
- AC1.1: The "Create a new template" option is accessible from the Office Add-in panel
- AC1.2: The form displays the title "Create a new template" with subtitle "Turn your current document into a standard template"
- AC1.3: All form fields are displayed on the same screen (not separate steps)

### FR002: Template Metadata Input
**Priority:** High  
**Description:** User must be able to enter template name, select template type, select template subtype, and add a note or description.

**Acceptance Criteria:**
- AC2.1: Template name field is a text input type
- AC2.2: Template type is a selectable dropdown/select field
- AC2.3: Template subtype is a selectable dropdown/select field
- AC2.4: Note/description field is a multi-line text area
- AC2.5: All fields are visible on the same screen

### FR003: Auto Detect Variables Button
**Priority:** High  
**Description:** A "Auto Detect Variables" CTA button must be provided that triggers AI-powered variable detection from the document.

**Acceptance Criteria:**
- AC3.1: "Auto Detect Variables" button is displayed below the template metadata fields
- AC3.2: Button is disabled until user enters template details (name, type, subtype)
- AC3.3: On click, the system calls AI LLM service to identify variables
- AC3.4: Document content is passed to the AI service
- AC3.5: Loading indicator is shown during AI processing

### FR004: AI Variable Detection
**Priority:** High  
**Description:** AI must process the document and identify at least 80% of variables. If detection is below 80% or 0%, user must be prompted to define variables manually.

**Acceptance Criteria:**
- AC4.1: AI processes the document content and identifies variables
- AC4.2: System validates that AI identified at least 80% of variables
- AC4.3: If AI detects 0% or less than 80% variables, system prompts user: "Ask user to define it manually"
- AC4.4: If document is empty when "Auto Detect Variables" is clicked, system prompts: "Ask user to upload a document"
- AC4.5: If document contains no variables (plain text only), system prompts: "Ask user to define it manually"

### FR005: Variable Detection Information Display
**Priority:** High  
**Description:** System must display information about the number of variables identified.

**Acceptance Criteria:**
- AC5.1: After AI processing, system displays message: "We have identified X number of variables in the document"
- AC5.2: Variables are displayed as a list (not inline in document)
- AC5.3: User can view all detected variables in the list

### FR006: Variable Processing and Formatting
**Priority:** High  
**Description:** System must process the template and format variables with the pattern [variable name].

**Acceptance Criteria:**
- AC6.1: Detected variables are processed and formatted as [variable name] in the template
- AC6.2: Variables replace the original text in the document with [variable name] format
- AC6.3: User can manually add/edit variables in the document itself if AI didn't detect them

### FR007: Variable Confirmation Checkbox
**Priority:** High  
**Description:** User must confirm that detected and custom added variables are correct before proceeding.

**Acceptance Criteria:**
- AC7.1: Checkbox is displayed below the "Auto Detect Variables" CTA with text: "I confirm the detected and custom added variables"
- AC7.2: Checkbox is unchecked by default
- AC7.3: User must check the checkbox to enable "Create Template" button

### FR008: Create Template Button
**Priority:** High  
**Description:** "Create Template" button must save the template with variables to the database.

**Acceptance Criteria:**
- AC8.1: "Create Template" button is displayed side by side with "Choose Existing Template" button
- AC8.2: "Create Template" button is disabled until user confirms variables (checkbox checked)
- AC8.3: On click, system saves template name, type, subtype, description, and all variables to database
- AC8.4: Variables are saved against the template name in database
- AC8.5: After successful save, system transitions to Journey 1.2 (Update Master Template) flow

### FR009: Choose Existing Template Button
**Priority:** Medium  
**Description:** "Choose Existing Template" button must be available at any time and navigate to Journey 1.3.

**Acceptance Criteria:**
- AC9.1: "Choose Existing Template" button is displayed side by side with "Create Template" button
- AC9.2: Button is available at any time (not dependent on variable detection)
- AC9.3: On click, system navigates to Journey 1.3 (Fill Form with Variables)

### FR010: Template Auto-Save
**Priority:** Medium  
**Description:** If user creates a template and then goes back to create another, the previous template must be saved automatically.

**Acceptance Criteria:**
- AC10.1: When user creates a template and navigates away, template is automatically saved
- AC10.2: User cannot create multiple templates from the same document in one session
- AC10.3: If user attempts to create another template, previous template is saved first

---

## 3. Non-Functional Requirements

### NFR001: Performance
- Template creation must complete in less than 1 minute from start to finish
- AI variable detection must complete within 10 seconds for documents up to 5MB
- UI must remain responsive during AI processing

### NFR002: Usability
- All form fields must be accessible and clearly labeled
- Error messages must be clear and actionable
- Loading indicators must be shown during async operations
- UI must follow the provided screenshot/mockup design

### NFR003: Reliability
- System must handle AI service failures gracefully (fallback to manual entry)
- Empty document validation must prevent invalid operations
- Database save operations must be transactional and atomic

### NFR004: Accuracy
- AI must identify at least 80% of variables to be considered successful
- Variable detection accuracy must be validated before allowing template creation

---

## 4. User Journeys

### 4.1 Primary User Journey: Create New Template

**Actor:** Lawyer/Paralegal/Legal Assistant

**Preconditions:**
- User has Word document open
- Office Add-in is loaded on the left side of the document
- Document contains content (not empty)

**Steps:**
1. User clicks "Create a new template" option in the add-in panel
2. System displays template creation form with fields:
   - Template name (text input)
   - Template type (dropdown)
   - Template subtype (dropdown)
   - Note/description (text area)
3. User enters template name, selects type and subtype, adds description
4. "Auto Detect Variables" button becomes enabled
5. User clicks "Auto Detect Variables"
6. System shows loading indicator
7. System calls AI LLM service with document content
8. AI processes document and identifies variables (≥80% threshold)
9. System displays: "We have identified X number of variables in the document"
10. System processes template and formats variables as [variable name]
11. Variables are displayed as a list
12. User reviews variables and can manually add/edit in document if needed
13. User checks "I confirm the detected and custom added variables" checkbox
14. "Create Template" button becomes enabled
15. User clicks "Create Template"
16. System saves template with all variables to database
17. System transitions to Journey 1.2 (Update Master Template) or shows success message

**Alternative Flows:**
- **A1:** AI detects <80% variables → System prompts user to define manually
- **A2:** Document is empty → System prompts user to upload a document
- **A3:** Document has no variables → System prompts user to define manually
- **A4:** User clicks "Choose Existing Template" → Navigate to Journey 1.3
- **A5:** User doesn't confirm checkbox → "Create Template" button remains disabled

**Postconditions:**
- Template is saved in database with all variables
- User can proceed to Journey 1.2 or Journey 1.3

---

## 5. UX Design Principles

### 5.1 Layout
- All form fields displayed on the same screen (no multi-step wizard)
- Form follows the provided screenshot/mockup design
- Office Add-in panel appears on the left side of Word document

### 5.2 Interaction
- Buttons are disabled/enabled based on user actions and validations
- Loading indicators shown during async operations
- Clear error messages for validation failures
- Confirmation required before critical actions (template creation)

### 5.3 Information Display
- Variables displayed as a list (not inline)
- Variable count clearly communicated to user
- Status messages inform user of current state

### 5.4 Accessibility
- All form fields are clearly labeled
- Buttons have descriptive text
- Error messages are accessible and actionable

---

## 6. Dependencies

### 6.1 Workflow Dependencies
**Reference:** `docs/business-docs/01-project-overview.mdc`

- **Journey 1.2 (Update Master Template):** Referenced in step 9 of Journey 1.1. After creating a template, user may proceed to update the master template with new variables.
  - Integration Point: Template creation flow connects to template update flow
  - Required Coordination: Database schema must support template updates
  - Workflow-Specific Business Rules: Variables can be appended to existing templates

- **Journey 1.3 (Fill Form with Variables):** Referenced in step 10 of Journey 1.1. User can choose to fill form with variables instead of creating template.
  - Integration Point: "Choose Existing Template" button navigates to Journey 1.3
  - Required Coordination: Variable form must be able to load variables from templates
  - Workflow-Specific Business Rules: Form displays variables for user input

### 6.2 Technical Dependencies
- **AI LLM Service:** Required for variable detection (existing service in `backend/src/ollama.rs`)
- **Database:** Required for template and variable storage (existing migrations in `backend/migrations/`)
- **Word Add-in API:** Required for document content extraction (existing in `word-extension/src/services/documentExtraction.ts`)
- **Backend API:** Required for template creation endpoint (existing handlers in `backend/src/handlers.rs`)

### 6.3 Data Dependencies
- Template metadata (name, type, subtype, description)
- Document content (for AI processing)
- Detected variables list
- User confirmation status

---

## 7. Impact Analysis

### 7.1 Impact on Existing Workflows

**Journey 1.2 (Update Master Template):**
- **Impact:** Journey 1.1 creates templates that Journey 1.2 can update
- **Required Changes:** None (Journey 1.2 already designed to work with existing templates)
- **Coordination Required:** Ensure template data structure is consistent between journeys

**Journey 1.3 (Fill Form with Variables):**
- **Impact:** Journey 1.1 creates templates that Journey 1.3 can use for form filling
- **Required Changes:** None (Journey 1.3 already designed to load variables from templates)
- **Coordination Required:** Ensure variable format [variable name] is consistent

### 7.2 Impact on Existing Systems

**Database:**
- **Impact:** New templates and variables will be stored
- **Required Changes:** Verify existing schema supports template creation (variables table exists)
- **Risk:** Ensure proper indexing for template lookup performance

**AI Service:**
- **Impact:** Increased usage of AI variable detection service
- **Required Changes:** Ensure service can handle concurrent requests
- **Risk:** AI service availability and response time

**Word Add-in:**
- **Impact:** New UI components for template creation form
- **Required Changes:** Add new React components for form and variable list
- **Risk:** UI performance with large variable lists

### 7.3 Potential Side Effects

- **Template Naming Conflicts:** Multiple users may create templates with same name
- **Variable Detection Accuracy:** AI may miss variables or detect false positives
- **Database Performance:** Large number of templates may impact query performance

### 7.4 Risk Assessment

**High Risk:**
- AI variable detection accuracy (80% threshold may not be achievable in all cases)
- User confirmation workflow dependency (if user doesn't confirm, template cannot be created)

**Medium Risk:**
- Template naming and type selection validation
- Database save operations reliability
- AI service availability and response time

**Low Risk:**
- UI component rendering performance
- Form field validation edge cases

---

## 8. Out of Scope

The following are explicitly **OUT OF SCOPE** for Journey 1.1:

1. **Template Deletion:** Users cannot delete templates in this journey
2. **Template Sharing:** Templates cannot be shared between users
3. **Template Editing:** Users cannot edit existing templates (only create new ones)
4. **Template Management:** No template management features (listing, searching, filtering)
5. **Variable Management:** No separate variable management interface (variables edited in document)
6. **Document Preview:** No preview of final document with variables filled
7. **Template Versioning:** No version control for templates
8. **Template Import/Export:** No import or export functionality

**Note:** If user edits variables in the document itself (using [variable name] format), those changes should sync against the template. This is the only exception for variable editing.

---

## 9. Success Criteria

### 9.1 Primary Success Metric
- **Time to Create Template:** User should be able to draft a template in less than 1 minute from start to finish

### 9.2 Secondary Success Metrics
- **AI Detection Accuracy:** AI successfully identifies ≥80% of variables in ≥90% of cases
- **User Adoption:** ≥80% of users successfully create their first template without errors
- **Error Rate:** <5% of template creation attempts result in errors
- **User Satisfaction:** Users report template creation is faster than manual process

### 9.3 Acceptance Criteria Summary
- All functional requirements (FR001-FR010) are implemented and tested
- All non-functional requirements (NFR001-NFR004) are met
- User journey can be completed in <1 minute
- Integration with Journey 1.2 and Journey 1.3 is functional
- Database schema supports template and variable storage

---

## 10. Assumptions

1. Document content is available and extractable from Word document
2. AI LLM service is available and responsive
3. Database is available and can store templates and variables
4. User has valid Word document open with content
5. Office Add-in is properly loaded and functional
6. User understands the concept of variables in templates
7. Template types and subtypes are predefined in the system

---

## 11. Open Questions

1. What are the available template types and subtypes? (Need to define the list)
2. What is the maximum number of variables a template can have?
3. What happens if template name already exists? (Allow duplicate names or require unique?)
4. Should there be a character limit for template name, description?
5. What is the maximum document size for AI processing?
6. Should there be a limit on the number of templates a user can create?

---

## 12. References

- **Workflow Documentation:** `docs/business-docs/01-project-overview.mdc`
- **Clarifying Questions Answers:** `docs/clarifying_questions_answers.md`
- **UI Mockup/Screenshot:** `docs/business-docs/MSWord-screenshot.png`
- **Existing Backend Code:** `backend/src/handlers.rs`, `backend/src/ollama.rs`
- **Existing Frontend Code:** `word-extension/src/services/aiVariableService.ts`, `word-extension/src/services/documentExtraction.ts`
- **Database Schema:** `backend/migrations/20250127000001_create_variables_table.sql`

---

**Document Status:** Draft  
**Last Updated:** 2025-01-27  
**Next Review:** After PO Review
