# AutoDraft 1.2 — Clio-inspired legal-data architecture port

This release ports the Clio concepts that fit AutoDraft's product direction without attempting to clone Clio's billing, accounting, CRM, calendar, or practice-management breadth.

## Implemented

### Matters, contacts, and participants

- Contacts are durable person/company records independent of a matter.
- Matter Participants connect contacts to a matter using legal role keys and display roles.
- Participants can be marked client, primary-for-role, and represented by the firm.
- A matter summary exposes the primary client without flattening the contact into a string.

### Practice areas and matter stages

- Firm-wide Practice Areas are reusable configuration.
- Matter Stages must belong to a Practice Area; a matter cannot carry a stage without a practice area.
- Matter status (`open`, `pending`, `closed`, `archived`) remains separate from its customizable workflow stage.
- Stage changes have a dedicated timestamp so the taskpane can display days in the current stage.
- Changing/clearing a practice area safely clears an incompatible stage.
- Practice-area and stage configuration writes require admin/owner permissions.

### Typed field definitions and values

AutoDraft now separates reusable metadata from per-record data:

- `field_definitions`: semantic key, display label, scope, type, validation, formatting, options, aliases, practice area, matter type, and group/card.
- `matter_field_values`: the typed value for one matter.
- `contact_field_values`: the typed value for one contact.
- `field_groups`: card-like groupings with an optional legal role key.

Supported value types include text, long text, integer, decimal, currency, date, datetime, boolean, choice, multi-choice, email, phone, address, contact/matter/document references, and JSON.

Definition-level validation is deterministic and supports required values, picklist membership, numeric min/max, length limits, and regex patterns. Configuration writes are admin/owner-only; normal matter/contact value writes remain available to authorized staff.

### Compatibility bridge for existing Matter Facts

The existing conflict-aware `matter_facts` system is not removed. The migration:

1. adds `field_definition_id` to existing facts;
2. creates semantic field definitions from existing canonical fact keys;
3. attaches facts to those definitions; and
4. mirrors canonical values into the typed-value layer without promoting unresolved conflict candidates.

New accepted/resolved/derived facts continue syncing through the same bridge. This avoids two competing sources of truth while allowing legacy drafting and intake code to continue working.

### Document Sets and drafting-run lifecycle

- A Document Set is a reusable ordered collection of templates for a practice area/matter type.
- Draft set items point to templates.
- Publishing a set requires every template to have an immutable template-version snapshot.
- Published set versions pin exact `template_version_id` values so later edits do not silently change a released set.
- A matter-specific generation run records the selected release/items.
- The server enforces `Selection → Population → Review → Completed`; a run may fail from an in-progress state but cannot skip workflow stages.

### Transactional domain-event/outbox foundation

Core legal-data writes emit domain events inside the same PostgreSQL transaction. Events include matter, contact, participant, canonical field, fact conflict, practice area/stage, document-set, and generation-run changes. The outbox is tenant-isolated and provides the future integration boundary for signed webhooks or external connectors without making the legal-data transaction depend on an external service.

### Tenant and release safety

All new organization-owned tables carry `organization_id` and row-level security policies. Child document-set/version tables also carry tenant identity rather than relying only on a parent join. Schema configuration is permission-gated. The migration is additive and does not drop existing matter/template/intake tables.

## Word taskpane integration

The drafting workspace now contains a **Canonical legal data** panel that can:

- assign/create practice areas and stages;
- create reusable contacts and attach them to a matter by legal role;
- configure field cards and semantic field definitions;
- edit typed canonical matter values;
- create/publish immutable Document Sets;
- start and advance a matter-specific Selection/Population/Review run; and
- inspect the matter activity/domain-event stream.

## Deliberately not copied from Clio

This release does not implement Clio billing, trust accounting, timekeeping, payments, email/calendar, broad CRM, or financial reporting. AutoDraft remains focused on legal data, document automation, drafting, intake, Word reliability, and local/private AI.

## Validation boundary

Automated source/backend/corpus checks are included. A disposable real PostgreSQL instance is still required to execute the complete migration/RLS integration test, and Microsoft Word is still required for host-level taskpane behavior. Frontend dependency installation must be completed in an environment with the npm packages available before claiming a production webpack/Vitest build.
