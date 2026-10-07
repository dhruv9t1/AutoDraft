
1. Scope, behavior & goal
- What should happen if the user clicks "Create Template" but hasn't confirmed the checkbox?
Ans: Disable the button.

- Should "Choose Existing Template" be available at any time, or only after variable detection?
Ans: Any time.

- What happens if AI detects 0% or less than 80% of variables? Should the user still be able to proceed?
Ans: Ask user to define it manually.

2. User interface
- Where should the "Create a new template" button/link appear in the Office Add-in panel?
Ans: I have provided screenshot for UI look and feel.

- Should the template name, type, and subtype fields be on the same screen, or separate steps?
Ans: On the same screen.

- How should detected variables be displayed to the user (list, inline in document, both)?
Ans: List.

3. Default state
- When the user opens the add-in, what should be the default view?
Ans: Provided in the screenshot.

- Should the "Auto Detect Variables" button be enabled immediately, or only after entering template details?
Ans: Only after entering template details.

4. Integration (business logic)
- Can a user create multiple templates from the same document in one session?
Ans: No.

- If a user creates a template, then goes back and creates another, should the previous template be saved automatically?
Ans: Yes.

5. User roles & permissions
No roles and permissions required.

6. Edge cases (business/user perspective)
- What should happen if the document is empty when "Auto Detect Variables" is clicked?
Ans: Ask user to upload a document.

- What if the document contains no variables (just plain text)?
Ans: Ask user to define it manually.

- Should users be able to manually add/edit variables that AI didn't detect?
Ans: Yes, he will do it in document itself.

7. Scope & boundaries
- Is this Journey 1.1 only for creating NEW templates, or can users also edit existing templates here?
Ans: Only for creating NEW templates.

- What is explicitly OUT of scope for Journey 1.1? (e.g., template deletion, template sharing)
Ans: Template deletion, template sharing.

8. Business context
- Why is this feature needed now? What business problem does it solve?
Ans: To decrease the time taken to draft a template.

- Who are the primary users (lawyers, paralegals, legal assistants)?
Ans: Lawyers, paralegals, legal assistants.

- What would make this feature successful from a user perspective?
Ans: User should be able to draft a template in less than 1 minute.
