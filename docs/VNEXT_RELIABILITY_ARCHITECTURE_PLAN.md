Understood. I will **not use Deep Research** again for this. I used ordinary web research against current primary documentation and combined it with everything we've learned from AutoDraft itself, your runtime logs, the lawyer-firm ZIP, the previous build, and the failures you just found.

The next ZIP should be treated differently from the previous builds: **not as another feature bundle, but as a reliability release with a redesigned internal core.**

One qualification: nobody can truthfully guarantee that a non-trivial Word add-in has *zero* bugs. What I can do is make the next ZIP pass several independent verification stages and refuse to call a feature working merely because it compiles. The real Word-host checks on your Mac remain essential because Office.js behavior cannot be completely simulated outside Word.

# AutoDraft vNext — Reliability Architecture Plan

## 1. The next ZIP has one mission

The next ZIP should establish this invariant:

```
A feature is never shown as successful unless
AutoDraft can prove that it succeeded.
```

That changes several existing behaviors immediately.

```
AI failed
    ≠
No fields found

Candidate found
    ≠
Field identified

Field identified
    ≠
Word field linked

Intake question suggested
    ≠
Question sent to client

Draft generated
    ≠
Facts verified

Citation present
    ≠
Citation verified

Template saved
    ≠
Current document completed
```

These become architectural rules, not UI conventions.

---

# 2. Freeze feature expansion temporarily

For the next ZIP I would **not** add billing, advanced research, playbooks, complex document sets, production GPU infrastructure, autonomous agents, extensive integrations, or advanced analytics.

We first make these seven things dependable:

1. AI infrastructure.
2. Database/data contracts.
3. Smart Field Engine.
4. Word binding.
5. Lawyer-controlled Intake.
6. Matters/Documents/Templates.
7. Drafting and Review.

Everything else sits on those foundations.

---

# 3. First major refactor: thin `main.py`

We have already had bugs such as the missing `re` import inside `main.py`, intake logic mixed with routes, model calls scattered through the application, and frontend behavior coupled to backend implementation.

The next structure should move toward:

```
backend/
│
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   │
│   ├── api/
│   │   ├── health.py
│   │   ├── matters.py
│   │   ├── documents.py
│   │   ├── fields.py
│   │   ├── templates.py
│   │   ├── intake.py
│   │   ├── drafting.py
│   │   └── review.py
│   │
│   ├── domain/
│   │   ├── matters.py
│   │   ├── facts.py
│   │   ├── fields.py
│   │   ├── bindings.py
│   │   ├── intake.py
│   │   ├── templates.py
│   │   └── review.py
│   │
│   ├── services/
│   │   ├── matter_service.py
│   │   ├── document_service.py
│   │   ├── field_service.py
│   │   ├── intake_service.py
│   │   ├── template_service.py
│   │   ├── drafting_service.py
│   │   └── review_service.py
│   │
│   ├── ai/
│   │   ├── gateway.py
│   │   ├── health.py
│   │   ├── errors.py
│   │   ├── schemas.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── ollama.py
│   │   │   └── jev.py
│   │   └── prompts/
│   │
│   ├── fields/
│   │   ├── extraction.py
│   │   ├── normalization.py
│   │   ├── candidates.py
│   │   ├── classification.py
│   │   ├── grouping.py
│   │   ├── grounding.py
│   │   └── overlap.py
│   │
│   ├── repositories/
│   │   ├── matters.py
│   │   ├── facts.py
│   │   ├── templates.py
│   │   ├── intake.py
│   │   └── documents.py
│   │
│   ├── db/
│   │   ├── pool.py
│   │   └── codecs.py
│   │
│   └── security/
│
├── migrations/
└── tests/
```

`main.py` should basically configure the application, middleware, exception handlers and routers.

Business logic should not live there.

---

# 4. Fix the JSON/JSONB contract globally

This is the cause of the catastrophic:

```
undefined
undefined
undefined
...
```

client questionnaire.

`asyncpg` officially maps PostgreSQL `json` and `jsonb` to Python `str` by default and supports connection codecs for automatic JSON conversion. [MagicStack](https://magicstack.github.io/asyncpg/current/usage.html?utm_source=chatgpt.com)

So we fix it **once at the connection pool**, rather than scattering `json.loads()` around routes.

```
async def configure_connection(conn):    await conn.set_type_codec(        "json",        schema="pg_catalog",        encoder=json.dumps,        decoder=json.loads,    )    await conn.set_type_codec(        "jsonb",        schema="pg_catalog",        encoder=json.dumps,        decoder=json.loads,    )
```

The pool's `init` hook is specifically intended for connection initialization such as codecs. [MagicStack](https://magicstack.github.io/asyncpg/devel/api/?utm_source=chatgpt.com)

Then add hard runtime contracts:

```
class IntakeQuestion(BaseModel):    id: UUID    label: str    question_type: QuestionType    required: bool = False    help_text: str | None = None    fact_key: str | None = None
```

If the database somehow returns:

```
questions = "..."
```

instead of:

```
questions = [...]
```

the request should fail validation internally.

It should never reach the client page.

---

# 5. Add a database contract test specifically for this bug

Use a **real PostgreSQL database** in integration tests.

Test:

```
INSERT questionnaire
    ↓
questions stored as JSONB
    ↓
repository fetch
    ↓
Python value
    ↓
must be list
    ↓
API serialization
    ↓
JSON array
    ↓
browser
```

Assertions:

```
assert isinstance(form.questions, list)assert len(form.questions) == 5assert all(isinstance(q, IntakeQuestion) for q in form.questions)assert all(q.label for q in form.questions)
```

And frontend:

```
expect(screen.queryByText("undefined")).not.toBeInTheDocument();
```

This exact regression test remains permanently.

---

# 6. AI subsystem becomes a proper service

Now that you have `qwen3:4b` installed, the next build should stop treating an HTTP request to port 11434 as proof that AI works.

Startup/readiness should verify:

```
Ollama reachable?
       ↓
Configured model exists?
       ↓
Small structured-output request succeeds?
       ↓
Schema validates?
       ↓
AI ready
```

[Ollama API documentation](https://github.com/ollama/ollama/blob/main/docs/api.md?file=api.md\&utm_source=chatgpt.com) supports supplying a JSON schema through `format`, which is much better than asking a model to “please output valid JSON.” [GitHub](https://github.com/ollama/ollama/blob/main/docs/api.md?file=api.md\&utm_source=chatgpt.com)

---

# 7. Add AI health endpoints

Implement:

```
GET /api/health/live
GET /api/health/ready
GET /api/health/ai
```

Example:

```
{
  "provider": "ollama",
  "reachable": true,
  "configuredModel": "qwen3:4b",
  "modelAvailable": true,
  "structuredOutput": true,
  "ready": true
}
```

Frontend startup can display:

```
AutoDraft AI ready
```

or:

```
AI features unavailable

Manual fields, matters and templates remain available.
```

The whole application should not die because AI is offline.

---

# 8. Introduce typed AI errors

Create:

```
class AIError(AutoDraftError):    passclass AIProviderUnavailable(AIError):    passclass AIModelUnavailable(AIError):    passclass AIRequestTimeout(AIError):    passclass AIOutputInvalid(AIError):    passclass AIContextTooLarge(AIError):    pass
```

Then API responses become predictable.

Example:

```
{
  "error": {
    "code": "AI_MODEL_UNAVAILABLE",
    "message": "The configured AI model is unavailable.",
    "recoverable": true,
    "requestId": "..."
  }
}
```

No raw:

```
500 Internal Server Error
```

for a known dependency problem.

---

# 9. Central AI Gateway

No route should call Ollama directly.

```
class AIGateway:    field_decision    field_naming    drafting    review
```

Providers:

```
OllamaProvider       ← active now
JevDecisionProvider  ← optional later
HostedProvider       ← future
MockProvider         ← tests
```

Configuration:

```
AUTODRAFT_AI_PROVIDER=ollama

FIELD_MODEL=qwen3:4b
DRAFTING_MODEL=qwen3:4b
REVIEW_MODEL=qwen3:4b

OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Your criminal-law Qwen fine-tune stays outside the general field engine.

---

# 10. Jev does not block the next ZIP

We should prepare:

```
class DecisionProvider(Protocol):    async def classify_candidate(...): ...
```

But the next reliability ZIP should work perfectly without Jev.

Then later:

```
DecisionProvider
├── OllamaDecisionProvider
└── JevDecisionProvider
```

No Jev dependency should be allowed to break AutoDraft.

---

# 11. Rebuild Smart Field detection as stages

The existing concept of:

```
Document
→ AI
→ variables
```

is replaced.

```
WORD
 │
 ▼
STRUCTURAL EXTRACTION
 │
 ▼
NORMALIZED SHADOW DOCUMENT
 │
 ▼
GENERIC CANDIDATES
 │
 ▼
SEMANTIC CLASSIFICATION
 │
 ▼
SEMANTIC NAMING
 │
 ▼
GROUP / DEDUPLICATE
 │
 ▼
DETERMINISTIC GROUNDING
 │
 ▼
OVERLAP PLANNER
 │
 ▼
WORD BINDING PLAN
 │
 ▼
WORD MUTATION
 │
 ▼
POST-BIND VERIFICATION
```

This is the most important internal redesign.

---

# 12. Structural extraction

Do not send one 61,000-character blob to the model.

Frontend extracts:

```
interface DocumentSegment {
    segmentId: string;

    story:
        | "body"
        | "table"
        | "header"
        | "footer";

    paragraphIndex?: number;

    tableIndex?: number;
    rowIndex?: number;
    cellIndex?: number;

    text: string;
    normalizedText: string;

    existingControls: ExistingControl[];
}
```

For your 506-cell document, we then know exactly where each candidate originated.

---

# 13. Preserve original and normalized text separately

Borrow the good concept from the lawyer-firm project.

```
ORIGINAL
    │
    ├── exact Word text
    └── source offsets

NORMALIZED
    │
    ├── Unicode spaces normalized
    ├── NBSP normalized
    ├── Unicode digits normalized
    ├── punctuation normalization
    └── search representation
```

Never modify original text to make detection easier.

---

# 14. Generic candidate generation

No hard-coded:

```
Qualification
Cheque Number
Religion
Occupation
Designation
Institution
```

Instead:

```
Existing content control
Label/value structure
Table label/value structure
Placeholder
Repeated-value pattern
Formatting pattern
Typed-value pattern
AI candidate
```

A detected date means:

```
possible candidate
```

not:

```
field
```

---

# 15. Semantic classification is mandatory

This is how we eliminate the `404 variables` disaster.

Each candidate gets:

```
{
  "classification": "replaceable_value"
}
```

or:

```
static_text
heading
label
body_text
ambiguous
```

If semantic classification is unavailable:

```
DETECTION FAILED
```

Not:

```
404 fields
```

---

# 16. Field detection becomes transactional

This is critical.

Current danger:

```
AI batch 1 succeeds
AI batch 2 fails
AI batch 3 succeeds
...
partial fields written to Word
```

New design:

```
START DETECTION
      ↓
extract
      ↓
candidate generation
      ↓
semantic classification
      ↓
grounding
      ↓
binding plan
      ↓
VALIDATE COMPLETE PLAN
      ↓
only now:
      ↓
COMMIT WORD BINDINGS
```

Before commit:

```
Word has not changed.
```

If anything fails before commit:

```
Word remains unchanged.
```

---

# 17. Detection result state machine

Backend result:

```
type DetectionStatus =
    | "completed"
    | "completed_with_review"
    | "no_fields"
    | "unavailable"
    | "failed";
```

These cannot be conflated.

Frontend:

```
completed
12 fields found

completed_with_review
11 linked · 2 need review

no_fields
No reusable fields found

unavailable
Field detection unavailable

failed
Field detection couldn't be completed
```

---

# 18. Grounding is deterministic

AI can say:

```
"This is probably Client Name."
```

AI cannot say:

```
"Bind characters 184-207."
```

Grounding uses structural source information.

Search sequence:

```
exact source span
      ↓
exact text in source container
      ↓
case-normalized
      ↓
normalized whitespace
      ↓
Office ignoreSpace
      ↓
Office ignorePunct
      ↓
bounded reconstruction
      ↓
Needs review
```

Word supports `ignoreSpace` and `ignorePunct` search options, which gives us a supported fallback instead of arbitrary fuzzy search. [Microsoft Learn](https://learn.microsoft.com/en-us/javascript/api/word/word.interfaces.searchoptionsupdatedata?view=word-js-preview\&utm_source=chatgpt.com)

Never jump straight to:

```
search entire document
take first match
```

---

# 19. Repeated values need occurrence identity

Example:

```
AHMEDABAD
```

may appear 20 times.

Store:

```
{
  "fieldId": "...",
  "occurrenceId": "...",

  "source": {
    "story": "table",
    "tableIndex": 3,
    "rowIndex": 4,
    "cellIndex": 1,
    "paragraphIndex": 0,
    "start": 23,
    "end": 32
  }
}
```

Then one semantic field can have:

```
client.name

Occurrence 1 — opening paragraph
Occurrence 2 — table
Occurrence 3 — signature
Occurrence 4 — footer
```

---

# 20. Binding IDs are immutable

Canonical model:

```
Field ID
8b7...

Semantic key
client.name

Display label
Client Name

Binding ID
42f...

Content control tag
autodraft:42f...
```

Changing:

```
Client Name
```

to:

```
Customer Name
```

must not alter the binding.

---

# 21. Binding Planner

Before touching Word:

```
grounded occurrences
        ↓
sort longest-first
        ↓
detect overlaps
        ↓
detect existing controls
        ↓
resolve parent/child conflicts
        ↓
detect duplicate bindings
        ↓
construct immutable plan
```

Result:

```
interface BindingPlan {
    operations: BindingOperation[];
    conflicts: BindingConflict[];
    canCommit: boolean;
}
```

No `GeneralException` should be used as our collision detector.

---

# 22. Word operations must be serialized

Create:

```
class WordOperationQueue
```

All operations go through it:

```
Extract
Bind
Fill
Navigate
Comment
Rewrite
Restore
Capture
```

Never allow unrelated React components to execute competing `Word.run()` mutations.

---

# 23. Post-binding verification is mandatory

After inserting a control:

```
insert
  ↓
context.sync()
  ↓
reload controls
  ↓
find expected UUID tag
  ↓
check expected text/location
  ↓
success
```

Only then:

```
✓ Linked
```

Otherwise:

```
Needs review
```

or:

```
Not linked
```

No confidence percentages.

---

# 24. Add live binding events

Word exposes content-control `onDataChanged` and `onDeleted` events in WordApi 1.5. [Microsoft Learn](https://learn.microsoft.com/javascript/api/word/word.contentcontrol?view=word-js-preview\&utm_source=chatgpt.com)

So supported Word hosts should detect:

```
user edits bound value
```

and:

```
user deletes content control
```

immediately.

For example:

```
Matter value
ABC Ltd

Word value
ABC Industries Ltd

The value changed in Word.

[Update matter]
[Restore matter value]
[Ignore]
```

Deleted control:

```
Binding broken

[Relink]
```

---

# 25. Runtime Word capability service

Microsoft explicitly recommends runtime requirement-set checks because Office API availability varies by platform/version. [Microsoft Learn](https://learn.microsoft.com/office/dev/add-ins/develop/office-versions-and-requirement-sets?utm_source=chatgpt.com)

Create:

```
interface WordCapabilities {
    wordApi14: boolean;
    wordApi15: boolean;

    customXml: boolean;
    contentControlEvents: boolean;
    comments: boolean;

    compressedDocumentCapture: boolean;
    desktopTrackChanges: boolean;
}
```

Every advanced feature consults this.

No assumptions about:

```
Mac == Windows == Web
```

---

# 26. Embedded AutoDraft document identity

WordApi 1.4 exposes `document.customXmlParts`. [Microsoft Learn](https://learn.microsoft.com/javascript/api/word/word.document?utm_source=chatgpt.com)

Use an AutoDraft manifest:

```
<autodraft schemaVersion="1">
    <documentId>...</documentId>
    <matterId>...</matterId>
    <templateId>...</templateId>

    <bindings>
       ...
    </bindings>
</autodraft>
```

This allows us to identify a managed document after:

```
rename
move
email
reopen
```

without relying solely on filename.

---

# 27. Reconcile document state at startup

When AutoDraft opens:

```
Embedded manifest
       +
Word controls
       +
Backend records
       ↓
RECONCILIATION
```

Possible result:

```
Healthy
Broken binding
Unexpected control
Missing backend binding
Outdated manifest
```

Then repair deliberately.

---

# 28. Full DOCX capture

On Word Windows and Mac, `getFileAsync(Office.FileType.Compressed)` can retrieve the complete DOCX package. Microsoft currently documents compressed Word retrieval on Windows and Mac, but not Word on the web. [Microsoft Learn](https://learn.microsoft.com/en-us/javascript/api/office/office.document?view=office-js\&utm_source=chatgpt.com)

Therefore template capture should be:

```
Desktop Word
   ↓
complete DOCX snapshot

Fallback where unsupported
   ↓
reduced capability
```

Do not pretend body OOXML equals the whole Word document.

---

# 29. Matter Documents becomes first-class

Each matter gets:

```
Documents

Current
────────────────
Real Corporation.docx
Open in Word

Matter documents
────────────────
Notice.docx
Complaint.docx
Agreement.docx

[Open] [Rename] [Archive]

+ Add document
+ Create from template
```

We should **not** build the UX around enumerating arbitrary open Word documents.

Instead, AutoDraft manages its own matter-document repository.

---

# 30. Opening a stored Matter Document

WordApi 1.3 supports creating a document from Base64 DOCX content. [Microsoft Learn](https://learn.microsoft.com/en-us/javascript/api/word/word.application?view=word-js-preview\&utm_source=chatgpt.com)

Therefore:

```
Matter document
     ↓
backend/storage
     ↓
DOCX
     ↓
Base64
     ↓
Word.Application.createDocument()
     ↓
Word opens document
```

This directly solves the workflow you complained about.

---

# 31. Intake is completely redesigned

Remove the hard-coded fallback questionnaire.

Completely.

No:

```
Client full legal name
Opposing party
What happened?
What relief?
```

unless the lawyer explicitly creates/accepts those questions.

---

# 32. Questionnaire ownership

New rule:

> AutoDraft can suggest. The lawyer publishes.

Flow:

```
Lawyer creates questionnaire
          ↓
Add questions manually
          ↓
optional:
Suggest with AutoDraft
          ↓
AI suggestions shown as DRAFTS
          ↓
lawyer accepts/edits/deletes
          ↓
Preview
          ↓
Publish
          ↓
Client link
```

This is consistent with the mature questionnaire pattern: current [Clio Draft questionnaire documentation](https://help.clio.com/hc/en-us/articles/24663592578075-Clio-Draft-Create-Questionnaire-Templates?utm_source=chatgpt.com) describes generated questions followed by customization, field mapping, sections, reordering and display logic. [help.clio.com](https://help.clio.com/hc/en-us/articles/24663592578075-Clio-Draft-Create-Questionnaire-Templates)

We should go one step more conservative: AI-generated questions remain explicitly unapproved until the lawyer accepts them.

---

# 33. Intake Builder

Question:

```
Question
─────────────────────────────
What date was the agreement signed?

Type
Date ▾

Requirement
● Required
○ Optional

Map answer to
agreement.execution_date ▾

Help text
[                              ]

Conditional display
Always ▾

[Delete]              [Save]
```

Question types:

```
Short text
Long text
Date
Number
Currency
Yes / No
Single choice
Multiple choice
Address
Person
File upload
```

---

# 34. Sections and ordering

Questionnaire:

```
CLIENT DETAILS
  Name
  Address

TRANSACTION
  Agreement date
  Amount

DOCUMENTS
  Upload agreement
```

Drag/drop ordering.

Sections can be reordered.

Questions can move between sections.

This is already a mature pattern in current questionnaire tooling. [help.clio.com](https://help.clio.com/hc/en-us/articles/41950759914907-Clio-Draft-Manage-and-Edit-Questionnaire-Templates?utm_source=chatgpt.com)

---

# 35. Required/Optional is explicit

Client form:

```
Agreement date
Required

[ DD / MM / YYYY ]
```

and:

```
Additional comments
Optional

[                    ]
```

W3C guidance recommends visibly identifying required fields and programmatically marking them as required rather than relying solely on an asterisk. [W3C](https://www.w3.org/WAI/tutorials/forms/validation/?utm_source=chatgpt.com)

So the HTML also uses:

```
required
aria-required="true"
```

where appropriate.

---

# 36. Proper validation

Submission error:

```
2 answers need attention

• Agreement date is required.
• Amount claimed is required.
```

Each item links/focuses the relevant field.

W3C recommends an accessible error summary identifying the corresponding field and explaining how to correct it. [W3C](https://www.w3.org/WAI/tutorials/forms/notifications/?utm_source=chatgpt.com)

No more:

```
Please complete all required fields.
```

with no explanation.

---

# 37. Intake versions

Once a questionnaire is sent to a client, edits should not silently alter the live version.

Use:

```
Questionnaire Template
        ↓
Version 1
        ↓
Published Intake Session
```

Changes create:

```
Version 2
```

Existing client session remains Version 1.

This also mirrors the safer behavior of mature questionnaire systems where template changes don't silently rewrite already-shared questionnaires. [help.clio.com](https://help.clio.com/hc/en-us/articles/41950759914907-Clio-Draft-Manage-and-Edit-Questionnaire-Templates?utm_source=chatgpt.com)

---

# 38. Intake data model

```
questionnaire_templates
questionnaire_versions
questionnaire_sections
questionnaire_questions

intake_sessions
intake_session_questions
intake_answers
```

Question fields include:

```
id
section_id
position

label
help_text

question_type
required

fact_key nullable

display_rule JSONB nullable
validation JSONB

created_at
updated_at
```

---

# 39. Matter Facts remain separate from Intake Questions

This distinction is important.

```
QUESTION
"What date was the agreement signed?"

          ↓ answer

MATTER FACT
agreement.execution_date

          ↓ used by

FIELD
Execution Date

          ↓ occurs in

WORD BINDINGS
paragraph 12
signature table
header
```

That's the proper chain.

---

# 40. Client answers are not automatically trusted

After submission:

```
Client Intake Received

18 answers

15 ready to import
2 need confirmation
1 conflicts with existing matter data

[Review responses]
```

Then lawyer confirms.

---

# 41. Conditional Intake comes after Builder stability

Once basic intake is proven, add deterministic display rules.

Current mature questionnaire systems support conditional display, and dependency-driven systems such as docassemble resolve missing information based on dependencies rather than forcing one fixed sequence. [help.clio.com](https://help.clio.com/hc/en-us/articles/24663592578075-Clio-Draft-Create-Questionnaire-Templates)

But this is **P1**, not the first thing I will build.

---

# 42. Matter model

```
Matter
│
├── Overview
├── People
├── Facts
├── Documents
├── Intake
├── Templates
├── Drafts
├── Authorities
└── Activity
```

Matter becomes the central object.

---

# 43. Facts

```
matter_facts

id
matter_id

fact_key
label

value_type
value_text
value_json

status

source_type
source_reference

created_at
updated_at
```

Statuses:

```
confirmed
user_entered
client_provided
document_extracted
ai_suggested
needs_confirmation
conflicted
```

---

# 44. Conflicting facts

Never silently overwrite:

```
Document:
₹30,000

Client intake:
₹35,000
```

Show:

```
Amount conflict

Document           ₹30,000
Client response    ₹35,000

[Use ₹30,000]
[Use ₹35,000]
[Enter another value]
```

---

# 45. Templates

Strictly separate:

```
Current Word document
Template
Template version
Field
Binding
Matter fact
```

Template:

```
Template
├── DOCX master
├── Versions
├── Fields
├── Bindings
└── Metadata
```

Conditions/repeaters come after reliability.

---

# 46. Template actions

Implement cleanly:

```
Use
Open
Rename
Duplicate
Archive/Delete
Capture current document
```

No forced:

```
Save Empty Template & Complete
```

Completing the current document does not require creating a reusable template.

---

# 47. Repeating data is P2

We absolutely need eventually:

```
directors[]
properties[]
employment[]
education[]
invoice_items[]
witnesses[]
```

HotDocs, for example, treats repeated regions as a first-class concept, including repeated table content. [help.hotdocs.com](https://help.hotdocs.com/author/current/Repeated_Region_Overview.htm?utm_source=chatgpt.com)

But we should not introduce repeaters until single-field bindings are reliable.

---

# 48. Conditions are deterministic, not AI-driven

Eventually:

```
{
  "and": [
    {"eq": ["client.type", "company"]},
    {"exists": "client.registration_number"}
  ]
}
```

Current document-automation systems use deterministic conditional regions rather than asking an LLM each time whether a clause belongs. [help.hotdocs.com](https://help.hotdocs.com/author/current/Creating_a_Conditional_Region.htm?utm_source=chatgpt.com)

Again: schema preparation now; full authoring UI later.

---

# 49. Drafting redesign

Actions stay independent:

```
Ask AutoDraft
Draft complete document
Draft section
Rewrite selection
Review document
```

Each has its own state.

Never:

```
isDrafting = true
```

for everything.

---

# 50. Drafting state machine

```
idle
 ↓
validating
 ↓
loading_context
 ↓
planning
 ↓
waiting_for_information
 ↓
generating
 ↓
reviewing
 ↓
ready
```

Failure:

```
model_unavailable
timeout
invalid_output
cancelled
failed
```

---

# 51. Drafting pipeline

```
Request
  ↓
Matter authorization
  ↓
Load confirmed facts
  ↓
Load current document
  ↓
Load optional authorities
  ↓
Build trusted context
  ↓
Plan
  ↓
Missing information?
  ├── yes → ask lawyer
  └── no
       ↓
Draft
       ↓
Sanitize citations
       ↓
Consistency review
       ↓
Structured response
```

---

# 52. Missing information is not Client Intake

Important distinction.

During drafting:

```
AutoDraft needs 2 details

Incident date
[             ]

Claim amount
[             ]

[Update matter and continue]
```

This is lawyer-facing.

Client Intake is a separate workflow.

---

# 53. Structured drafting output

Use schema-constrained output where possible:

```
class DraftResult(BaseModel):    draft: str    missing_information: list[MissingFact]    review_findings: list[ReviewFinding]    citation_status: CitationStatus    citations: list[CitationFinding]
```

The current Ollama API supports schema-based structured output, so we should use it rather than repeatedly attempting to repair malformed JSON. [GitHub](https://github.com/ollama/ollama/blob/main/docs/api.md?file=api.md\&utm_source=chatgpt.com)

---

# 54. Review

Rename:

```
QA Review
```

to:

```
Document Review
```

Schema:

```
interface ReviewFinding {
    id: string;

    category:
      | "missing_information"
      | "field_connection"
      | "document_consistency"
      | "drafting"
      | "authority"
      | "formatting";

    severity:
      | "info"
      | "review"
      | "important";

    title: string;
    detail: string;

    location?: DocumentLocation;
    suggestedAction?: string;
}
```

This eliminates `[object Object]` by design.

---

# 55. Native Word comments are a later enhancement

Word supports `Range.insertComment()` in WordApi 1.4. [Microsoft Learn](https://learn.microsoft.com/en-us/javascript/api/word/word.range?view=word-js-preview\&utm_source=chatgpt.com)

So eventually:

```
Review finding
      ↓
sidebar
      +
Word comment
```

But first make structured sidebar findings reliable.

---

# 56. Track Changes is capability-gated

The current Word JavaScript API exposes `trackRevisions`, but it is under `WordApiDesktop 1.4`. [Microsoft Learn](https://learn.microsoft.com/javascript/api/word/word.document?utm_source=chatgpt.com)

Therefore:

```
desktop supports it
      ↓
Rewrite with Track Changes

unsupported host
      ↓
preview replacement instead
```

No unconditional API calls.

---

# 57. Citation semantics

Allowed states only:

```
not_applicable
not_checked
needs_verification
partially_verified
verified
```

Never:

```
Pass
Verified authorities: 0
```

If there are no citations:

```
No citations to review
```

If citations exist but no authority corpus was checked:

```
Authority verification required
```

---

# 58. Security stays in the architecture now

Even if authentication isn't the immediate local-development blocker, repository/service APIs should already take organization/matter context.

Future production requests such as:

```
GET /matters/{matter_id}
```

must perform object authorization.

OWASP specifically identifies object-level authorization as a major API risk and recommends permission checks on every operation using client-supplied object IDs. [OWASP API Security Top 10](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/?utm_source=chatgpt.com)

---

# 59. Prompt injection boundaries remain

Treat:

```
Word document
client answers
uploaded precedent
PDF
retrieved authority
```

as untrusted data.

OWASP recommends segregating external content, limiting model privileges and requiring human approval for high-risk actions. [OWASP Gen AI Security Project](https://genai.owasp.org/llmrisk/llm01-prompt-injection/?utm_source=chatgpt.com)

So:

```
AI recommends replacement
       ↓
lawyer approves
       ↓
AutoDraft modifies Word
```

for destructive/high-impact operations.

---

# 60. Supabase architecture later

If we move to [Supabase](https://supabase.com/docs/guides/security/product-security?utm_source=chatgpt.com), every exposed table must have appropriate RLS/grants. Current Supabase guidance explicitly says exposed tables without RLS can be accessible to roles holding grants and recommends RLS plus operation-specific policies/tests. [Supabase](https://supabase.com/docs/guides/database/postgres/row-level-security?utm_source=chatgpt.com)

Storage should also use private buckets/RLS; the service/secret key must remain server-side. [Supabase](https://supabase.com/docs/guides/storage/security/access-control?utm_source=chatgpt.com)

We design IDs/organization boundaries now so migration later is straightforward.

---

# 61. Frontend restructuring

```
word-extension/src/

app/

features/
    matters/
    documents/
    fields/
    templates/
    intake/
    drafting/
    review/

services/
    api/
        apiClient.ts

    word/
        capabilityService.ts
        documentExtraction.ts
        documentIdentity.ts
        documentSnapshot.ts
        bindingPlanner.ts
        bindingService.ts
        eventService.ts
        operationQueue.ts
        navigationService.ts

state/
    matterStore.ts
    documentStore.ts
    operationStore.ts

types/
```

React components should not directly contain complex Office.js operations.

---

# 62. Central typed API client

Every frontend request goes through:

```
apiClient
```

Response:

```
type ApiResult<T> =
  | {
      ok: true;
      data: T;
      requestId: string;
    }
  | {
      ok: false;
      error: ApiError;
      requestId: string;
    };
```

No random `fetch()` parsing scattered across components.

---

# 63. Stale operation protection

Every long operation receives:

```
runId
```

If detection #18 finishes after detection #19 started:

```
#18 result discarded
```

This good pattern from the lawyer-firm codebase should become standard throughout AutoDraft.&#x20;

---

# 64. Golden Document Corpus

Before choosing whether field detection is “good,” create sanitized fixtures.

```
01-simple-cv.docx
02-formatted-cv.docx
03-table-heavy.docx
04-legal-notice.docx
05-affidavit.docx
06-agreement.docx
07-complaint.docx
08-invoice.docx
09-header-footer.docx
10-repeated-values.docx
11-split-formatting.docx
12-existing-controls.docx
13-nested-tables.docx
14-large-500-cell.docx
15-multilingual.docx
16-no-fields.docx
```

No confidential client documents in Git.

---

# 65. Ground truth

Every test document gets an annotation file.

```
{
  "fields": [
    {
      "semanticKey": "person.name",
      "sourceText": "Dhruv Purohit",
      "segment": "...",
      "replaceable": true
    }
  ],

  "mustNotDetect": [
    "CURRICULUM VITAE",
    "EDUCATION"
  ]
}
```

---

# 66. Real metrics

We measure:

```
Semantic precision
Semantic recall
Semantic F1

Grounding success

Duplicate rate
Overlap failure rate

Binding-plan success
Actual Word binding success
Post-bind verification success

Latency
AI calls
```

No user-facing:

```
96.0495% identification
```

That number is not meaningful product quality.

---

# 67. Fault-injection tests

This is new and important.

We deliberately break dependencies.

### Ollama stopped

Expected:

```
503 controlled response
zero Word changes
zero fake fields
manual features remain usable
```

### Model missing

Expected:

```
AI_MODEL_UNAVAILABLE
```

### Ollama timeout

Expected:

```
AI_TIMEOUT
```

### Invalid structured response

Expected:

```
AI_OUTPUT_INVALID
zero Word changes
```

### PostgreSQL unavailable

Expected:

```
DATABASE_UNAVAILABLE
```

### One detection chunk fails

Expected:

```
entire semantic detection does not commit
```

This would have caught the exact 404→404-fields bug.

---

# 68. The next ZIP verification system

This is where I want to be substantially stricter than before.

The ZIP goes through **five passes**.

## PASS 1 — source validation

Backend:

```
python -m compileall -q app
python -c "from app.main import app; print('IMPORT OK')"
python -m pytest -v
```

Frontend:

```
npx tsc --noEmit
npx vitest run
npm run build:dev
```

No failures accepted.

---

# 69. PASS 2 — real integration environment

Not mocked PostgreSQL.

Start actual:

```
PostgreSQL
FastAPI
Ollama
qwen3:4b
```

Test:

```
JSONB round-trip
migrations
matter create/read/update
questionnaire save/load
intake publish
intake submit
template lifecycle
Ask AutoDraft
Draft Complete
field detection
```

This is particularly important because the previous JSONB bug would not necessarily appear in a mocked DB layer.

---

# 70. PASS 3 — adversarial/failure suite

Run:

```
Ollama off
wrong model
AI timeout
malformed model response
database failure
empty document
huge document
zero fields
hundreds of candidates
duplicate fields
repeated values
split formatting
existing controls
overlapping candidates
```

Expected result must always be truthful.

---

# 71. PASS 4 — clean release simulation

Create a completely new directory.

```
source tree
   ↓
release ZIP
   ↓
extract ZIP
   ↓
fresh directory
```

Then repeat:

```
Python environment creation
requirements installation
backend import
tests
npm install/ci
TypeScript
Vitest
frontend build
manifest validation
```

This catches files accidentally present only in my development tree.

---

# 72. PASS 5 — archive inspection

Reject ZIP if it contains:

```
.venv/
node_modules/
__pycache__/
.pytest_cache/
.env
API keys
database credentials
client documents
private PDFs
private DOCX
.git/
DS_Store
temporary logs
```

Then:

```
unzip -t AutoDraft.zip
shasum -a 256 AutoDraft.zip
```

Record SHA-256.

---

# 73. Real Word verification

There is one thing I cannot truthfully replace with static tests:

**actual Microsoft Word behavior.**

So after automated verification, the candidate build goes to your Mac.

Mac Word smoke suite:

```
Open add-in
Select matter
Extract document
Detect fields
Link fields
Verify fields
Edit linked value
Delete linked control
Relink
Save template
Reopen template
Ask AutoDraft
Draft Complete
Client Intake
Open saved Matter Document
Restore after destructive draft
```

Only after that passes should we call the ZIP a release candidate.

Later repeat Windows.

Word Web gets capability-specific expectations because, for example, Microsoft currently documents compressed whole-document capture differently across platforms. [Microsoft Learn](https://learn.microsoft.com/en-us/javascript/api/office/office.document?view=office-js\&utm_source=chatgpt.com)

---

# 74. Known-bug regression matrix

Every bug you've already found becomes permanent test coverage.

```
BUG                                   MUST NEVER RETURN

Missing `re`                          intake 500
JSONB questions as string             undefined × 500
Ollama 404                            generic HTTP 500
AI chunk failure                      hundreds of fields
AI failure                            "No variables found"
Repeated text                         first random occurrence
Word wrap failure                     false ✓ Linked
Shared isDrafting                     both buttons spinning
Review object                         [object Object]
0 authorities                         "Verified"
Complete document                     forced template save
Heading                               automatically field
Rename field                          broken binding ID
Deleted content control               still ✓ Linked
```

This is one of the most valuable parts of the next build.

---

# 75. Migration testing

Take a copy/schema representing the previous AutoDraft database.

Run:

```
old schema
   ↓
all new migrations
   ↓
new schema
```

Verify:

```
matters preserved
templates preserved
bindings preserved
facts preserved
intake preserved
```

Binding IDs must never be regenerated unnecessarily.

---

# 76. Release blocker policy

The ZIP is **not shipped** when any of these happen:

```
Python test failure
TypeScript error
Vitest failure
frontend build failure
migration failure
JSONB contract failure
known regression
field detection commits after AI failure
unverified control shown Linked
generic 500 from known AI failure
undefined intake label
private file in archive
ZIP integrity failure
```

That's the standard I want to use.

---

# 77. What exactly goes into the NEXT ZIP

This is deliberately narrower than the full product roadmap.

### P0 — mandatory

```
Backend modularization foundation
JSON/JSONB codec
Pydantic contracts
AI Gateway
Ollama health/readiness
qwen3:4b structured output
typed AI errors
controlled 503s
request IDs

fail-closed field detection
structural candidate metadata
normalized shadow text
grouping/deduplication
grounding
overlap planner

Word operation queue
immutable binding IDs
post-bind verification
professional binding states

lawyer-owned Intake Builder
remove fallback questions
required/optional
question types
reordering
preview
publish
correct public form
correct validation

Matter selector cleanup
Matter Documents v1

template rename/delete/duplicate
completion independent of template save
layout recovery

independent drafting states
structured DraftResult
structured Document Review
truthful citation states

regression suite
golden corpus foundation
multi-pass release script
```

---

# 78. P1 — immediately after P0 proves stable

```
Custom XML document identity
binding reconciliation
content-control change/delete events
complete DOCX template snapshots
questionnaire sections
conditional intake
fact conflict UI
derived facts
native Word comments
```

Some of these may safely move into the next ZIP if implementation/testing is clean, but they should not delay the P0 reliability release.

---

# 79. P2

```
Jev provider
ambiguous-candidate secondary verifier
repeatable template regions
template conditional regions
dependency-driven intake
Track Changes drafting
document sets
uploaded-document knowledge
authoritative research connectors
playbooks
```

---

# 80. P3

```
production authentication
organizations
RBAC
Supabase/RLS if selected
production storage
audit administration
serverless/hosted inference
production monitoring
deployment
```

Some security foundations will exist earlier; this phase is production hardening.

---

# 81. Definition of Done for the next ZIP

I would not consider the next ZIP complete until all of these are true:

```
✓ qwen3:4b health check passes

✓ Ask AutoDraft works
✓ Draft Complete works

✓ AI unavailable produces controlled error
✓ AI unavailable cannot modify Word

✓ AI failure cannot create fallback fields

✓ No undefined intake labels
✓ No hard-coded intake questionnaire
✓ Lawyer controls every client question
✓ Required/Optional is obvious
✓ Exact validation errors are shown

✓ Candidate != Field
✓ Field != Binding
✓ Binding requires post-verification

✓ repeated values are occurrence-aware
✓ headings are not automatically fields
✓ overlaps are planned before Word mutation

✓ no confidence percentages

✓ Matter Documents exists
✓ saved matter document can be opened in Word

✓ current document completion does not force template creation

✓ [object Object] impossible through typed review rendering

✓ citation "verified" impossible without verification

✓ old database migrates successfully

✓ backend tests pass
✓ PostgreSQL integration tests pass
✓ TypeScript passes
✓ frontend tests pass
✓ build passes
✓ golden corpus passes agreed thresholds
✓ fault-injection tests pass

✓ clean ZIP re-extract passes verification again

✓ archive contains no dependencies/secrets/private docs
✓ unzip integrity passes
✓ SHA-256 supplied

✓ Mac Word smoke test passes
```

That is the target.

---

# 82. How I would execute the actual work

There is one change from how we worked previously that matters a lot.

I do **not** want to start from another remembered or intermediate AutoDraft source tree.

When we build, the input should be the **exact ZIP you're running right now**, including the build that produced the screenshots and logs you just showed me.

Then I will treat:

```
YOUR CURRENT ZIP
        +
LAWYER-FIRM ZIP
        +
KNOWN BUG MATRIX
        +
THIS ARCHITECTURE
        ↓
SOURCE COMPARISON
        ↓
IMPLEMENT
        ↓
TEST PASS 1
        ↓
TEST PASS 2
        ↓
FAULT TESTS
        ↓
REVIEW CODE AGAIN
        ↓
PACKAGE
        ↓
EXTRACT FRESH
        ↓
TEST AGAIN
        ↓
ARCHIVE AUDIT
        ↓
SHA-256
        ↓
YOUR MAC WORD TEST
```

as the release process.