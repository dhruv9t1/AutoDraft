### Category 1: Scope, behavior & goal
1. What problem does this feature solve for lawyers using the add-in?
- Drafting documents is a time consuming task for lawyers.
- This system will help lawyers to draft documents faster and more efficiently.
- This system will help lawyers to draft documents more accurately and more consistently.
- This system will help lawyers to draft documents more easily and more quickly.

2. What should happen after the AI identifies variables? (e.g., show a list, auto-fill a form, allow editing)
- In the next step, we will show a list of variables and ask the user to fill in the values in form, then again he selects the same template then we will load table view of variables, and allow to enter new values for variables.

3. Should users be able to select multiple templates, or only one at a time?
- Only one at a time.

4. What is the main goal: faster template creation, accuracy, or something else?
- Faster template creation, accuracy, user adoption.

### Category 2: User interface
5. Where should the "Add new template" option appear? (e.g., in the dropdown, a separate button, at the bottom of the list)
Ans: There in no such option. If he selects from creatable dropdown then it is existing, if he creates new one then it is new.

6. When a template is selected, what information should be shown? (e.g., template name, description, preview, variable count)
Ans: Template name only.

7. After clicking to identify variables, what should users see? (e.g., loading indicator, progress, results list)
Ans: Loading indicator and next screen will show the variables list with form if new or else table view of variables.

8. Should the template list show all templates or only recent/favorites?
Ans: Top 5 recently used templates.

### Category 3: Default state
9. When the add-in opens, should a template be pre-selected, or should the dropdown be empty?
Ans: Empty searchbar with createable dropdown.

10. If no template is selected, should the "Identify Variables" action be disabled?
Ans: Yes, if there is no template please disabled both "Identify Variables" and "Fill the form" buttons.

### Category 4: Integration (business logic)
11. How should this work with existing templates? (e.g., can users edit existing templates, or only create new ones?)
Ans: Let us always create new template if user adds or edits new variables in template.

12. Should identified variables be saved automatically, or require user confirmation?
Ans: Required user confirmation.

13. If a template already has variables defined, should the AI replace them or merge with existing ones?
Ans: Merge with existing ones.

### Category 5: User roles & permissions
No restrictions based on role, as for first release we only have one user type.

### Category 6: Edge cases (user perspective)
16. What should happen if the AI cannot identify variables (e.g., no variables found, unclear document)?
Ans: Ask user to manually identify.

17. What if the API call fails or times out? (e.g., show an error, allow retry, fallback to manual entry)
Ans: Fallback to manual entry.

18. What if a user selects a template but the document doesn't match? (e.g., wrong template type, empty document)
Ans: Show error message and ask user to select different template.

### Category 7: Scope & boundaries
19. Is this feature only for creating new documents, or also for editing existing ones?
Ans: Create new documents, reuse existing templates.

20. What is explicitly out of scope? (e.g., template management, variable editing, document preview)
Ans: Template management, variable management, document preview. But if user edits in document [variable] then it should sync in against the template.

### Category 8: Business context
21. Why is this needed now? (e.g., current process is slow, error-prone, time-consuming)
Ans: Current process is slow, error-prone, time-consuming.

22. Who benefits most from this feature? (e.g., all lawyers, specific practice areas, new users)
Ans: All lawyers.

23. What would make this feature successful? (e.g., time saved, accuracy, user adoption)
Ans: Time saved, accuracy, user adoption.
