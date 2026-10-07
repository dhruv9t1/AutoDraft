# Canonical data completion — 2026-10-06

This pass closes the remaining canonical-data gaps identified after the v1.3 deep audit.

## Universal legal-value write boundary

`app.services.legal_value_service.LegalValueWriteService` is now the shared write boundary for canonical matter/contact field values. Matter writes are conflict-aware by default, including manual field edits, workflow promotion, matter-fact compatibility writes and derived-rule output. Future intake/extraction/AI promotion code should call this service rather than writing canonical tables directly.

## Schema-change safety

Field definition updates now fail closed when persisted values exist and a `valueType` or `repeatable` change would require migration. Changes to options/validation/required metadata are accepted only when all persisted values remain valid under the proposed definition.

## Repeatable canonical fields

Repeatable values are stored as stable ordered instances in `matter_field_value_items` / `contact_field_value_items`. A collection PUT accepts either a simple array or item envelopes such as:

```json
[
  {"id":"<existing-item-uuid>","value":"first"},
  {"value":"new item"}
]
```

Existing item IDs are preserved; omitted item IDs are deleted; array order is persisted in `position`.

## Corrective typed backfill

Migration `20261006000023_canonical_data_completion.sql` populates typed number/boolean/date/datetime columns from legacy raw text where conversion is safe. Failed conversions are recorded in `field_value_migration_errors` and exposed to admins at `GET /api/field-migration-errors`.

## Practice area / stage integrity

PostgreSQL now enforces that a matter stage belongs to the exact `(organization_id, practice_area_id)` assigned to the matter using `fk_matters_practice_stage_compatible` plus a stage-requires-practice check.

## True reference fields

`contact_reference`, `matter_reference`, and `document_reference` now persist to dedicated UUID columns protected by tenant-aware foreign keys, for scalar and repeatable values. Application writes also validate target existence before persistence.
