-- SEC-004 completion + SEC-005: comprehensive tenant ownership and
-- database-enforced same-tenant relational integrity.
--
-- Public token bootstrap tables intentionally remain outside tenant RLS because
-- they are used to resolve a bearer token to an organization before tenant
-- context exists. All normal application/domain tables are tenant-owned.

-- Add tenant ownership to older child tables that previously inherited tenancy
-- only through a parent row. Runtime defaults use the fail-closed accessor, not
-- the historical Local AutoDraft organization constant.
ALTER TABLE variables ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE variables v SET organization_id=t.organization_id FROM templates t WHERE v.template_id=t.id AND v.organization_id IS NULL;
UPDATE variables SET organization_id='00000000-0000-0000-0000-000000000001'::uuid WHERE organization_id IS NULL;
ALTER TABLE variables ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE variables ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE activity_logs a SET organization_id=t.organization_id FROM templates t WHERE a.template_id=t.id AND a.organization_id IS NULL;
UPDATE activity_logs SET organization_id='00000000-0000-0000-0000-000000000001'::uuid WHERE organization_id IS NULL;
ALTER TABLE activity_logs ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE activity_logs ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE template_versions ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE template_versions tv SET organization_id=t.organization_id FROM templates t WHERE tv.template_id=t.id AND tv.organization_id IS NULL;
ALTER TABLE template_versions ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE template_versions ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE matter_facts mf SET organization_id=m.organization_id FROM matters m WHERE mf.matter_id=m.id AND mf.organization_id IS NULL;
ALTER TABLE matter_facts ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE matter_facts ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE matter_authorities ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE matter_authorities ma SET organization_id=m.organization_id FROM matters m WHERE ma.matter_id=m.id AND ma.organization_id IS NULL;
ALTER TABLE matter_authorities ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE matter_authorities ALTER COLUMN organization_id SET NOT NULL;

UPDATE audit_events ae SET organization_id=m.organization_id FROM matters m WHERE ae.matter_id=m.id AND ae.organization_id IS NULL;
UPDATE audit_events ae SET organization_id=u.organization_id FROM app_users u WHERE ae.actor_user_id=u.id AND ae.organization_id IS NULL;
UPDATE audit_events SET organization_id='00000000-0000-0000-0000-000000000001'::uuid WHERE organization_id IS NULL;
ALTER TABLE audit_events ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE audit_events ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE questionnaire_versions ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE questionnaire_versions qv SET organization_id=qt.organization_id FROM questionnaire_templates qt WHERE qv.template_id=qt.id AND qv.organization_id IS NULL;
ALTER TABLE questionnaire_versions ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE questionnaire_versions ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE questionnaire_sections ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE questionnaire_sections qs SET organization_id=qv.organization_id FROM questionnaire_versions qv WHERE qs.version_id=qv.id AND qs.organization_id IS NULL;
ALTER TABLE questionnaire_sections ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE questionnaire_sections ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE questionnaire_questions ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE questionnaire_questions qq SET organization_id=qv.organization_id FROM questionnaire_versions qv WHERE qq.version_id=qv.id AND qq.organization_id IS NULL;
ALTER TABLE questionnaire_questions ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE questionnaire_questions ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE intake_session_questions ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE intake_session_questions isq SET organization_id=s.organization_id FROM intake_sessions s WHERE isq.session_id=s.id AND isq.organization_id IS NULL;
ALTER TABLE intake_session_questions ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE intake_session_questions ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE intake_answers ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE intake_answers ia SET organization_id=s.organization_id FROM intake_sessions s WHERE ia.session_id=s.id AND ia.organization_id IS NULL;
ALTER TABLE intake_answers ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE intake_answers ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE fact_conflicts ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE fact_conflicts fc SET organization_id=m.organization_id FROM matters m WHERE fc.matter_id=m.id AND fc.organization_id IS NULL;
ALTER TABLE fact_conflicts ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE fact_conflicts ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE intake_files ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
UPDATE intake_files f SET organization_id=s.organization_id FROM intake_sessions s WHERE f.session_id=s.id AND f.organization_id IS NULL;
ALTER TABLE intake_files ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE intake_files ALTER COLUMN organization_id SET NOT NULL;

-- Direct tenant tables that predate the fail-closed hardening also receive the
-- fail-closed default for new rows where callers omit organization_id.
ALTER TABLE app_users ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();
ALTER TABLE intake_forms ALTER COLUMN organization_id SET DEFAULT autodraft_current_organization_id();

-- Every tenant parent exposes a unique (organization_id,id) key so child rows
-- can reference the parent identity and tenant in one database constraint.
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_org_id ON app_users(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_templates_org_id ON templates(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_versions_org_id ON template_versions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_matters_org_id ON matters(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_matter_facts_org_id ON matter_facts(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_matter_documents_org_id ON matter_documents(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_questionnaire_templates_org_id ON questionnaire_templates(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_questionnaire_versions_org_id ON questionnaire_versions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_questionnaire_sections_org_id ON questionnaire_sections(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_questionnaire_questions_org_id ON questionnaire_questions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_forms_org_id ON intake_forms(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_sessions_org_id ON intake_sessions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_practice_areas_org_id ON practice_areas(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_matter_stages_org_id ON matter_stages(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_org_id ON contacts(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_field_groups_org_id ON field_groups(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_field_definitions_org_id ON field_definitions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_document_sets_org_id ON document_sets(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_document_set_versions_org_id ON document_set_versions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_runs_org_id ON generation_runs(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workflows_org_id ON workflows(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_versions_org_id ON workflow_versions(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_sessions_org_id ON workflow_sessions(organization_id,id);

-- Add tenant-consistent foreign keys. Existing single-column foreign keys are
-- kept for backward compatibility; these composite keys close cross-tenant UUID
-- reference paths even if application code is malformed.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_variables_template_tenant') THEN
    ALTER TABLE variables ADD CONSTRAINT fk_variables_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_template_versions_template_tenant') THEN
    ALTER TABLE template_versions ADD CONSTRAINT fk_template_versions_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_facts_matter_tenant') THEN
    ALTER TABLE matter_facts ADD CONSTRAINT fk_matter_facts_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_authorities_matter_tenant') THEN
    ALTER TABLE matter_authorities ADD CONSTRAINT fk_matter_authorities_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_audit_events_actor_tenant') THEN
    ALTER TABLE audit_events ADD CONSTRAINT fk_audit_events_actor_tenant FOREIGN KEY (organization_id,actor_user_id) REFERENCES app_users(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_audit_events_matter_tenant') THEN
    ALTER TABLE audit_events ADD CONSTRAINT fk_audit_events_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_documents_matter_tenant') THEN
    ALTER TABLE matter_documents ADD CONSTRAINT fk_matter_documents_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_bindings_document_tenant') THEN
    ALTER TABLE document_bindings ADD CONSTRAINT fk_document_bindings_document_tenant FOREIGN KEY (organization_id,matter_document_id) REFERENCES matter_documents(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_bindings_template_tenant') THEN
    ALTER TABLE document_bindings ADD CONSTRAINT fk_document_bindings_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_questionnaire_versions_template_tenant') THEN
    ALTER TABLE questionnaire_versions ADD CONSTRAINT fk_questionnaire_versions_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES questionnaire_templates(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_questionnaire_sections_version_tenant') THEN
    ALTER TABLE questionnaire_sections ADD CONSTRAINT fk_questionnaire_sections_version_tenant FOREIGN KEY (organization_id,version_id) REFERENCES questionnaire_versions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_questionnaire_questions_version_tenant') THEN
    ALTER TABLE questionnaire_questions ADD CONSTRAINT fk_questionnaire_questions_version_tenant FOREIGN KEY (organization_id,version_id) REFERENCES questionnaire_versions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_questionnaire_questions_section_tenant') THEN
    ALTER TABLE questionnaire_questions ADD CONSTRAINT fk_questionnaire_questions_section_tenant FOREIGN KEY (organization_id,section_id) REFERENCES questionnaire_sections(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_public_legacy_intake_form_tenant') THEN
    ALTER TABLE public_legacy_intake_tokens ADD CONSTRAINT fk_public_legacy_intake_form_tenant FOREIGN KEY (organization_id,form_id) REFERENCES intake_forms(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_public_intake_session_tenant') THEN
    ALTER TABLE public_intake_tokens ADD CONSTRAINT fk_public_intake_session_tenant FOREIGN KEY (organization_id,session_id) REFERENCES intake_sessions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_sessions_questionnaire_tenant') THEN
    ALTER TABLE intake_sessions ADD CONSTRAINT fk_intake_sessions_questionnaire_tenant FOREIGN KEY (organization_id,questionnaire_version_id) REFERENCES questionnaire_versions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_sessions_matter_tenant') THEN
    ALTER TABLE intake_sessions ADD CONSTRAINT fk_intake_sessions_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_session_questions_session_tenant') THEN
    ALTER TABLE intake_session_questions ADD CONSTRAINT fk_intake_session_questions_session_tenant FOREIGN KEY (organization_id,session_id) REFERENCES intake_sessions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_session_questions_question_tenant') THEN
    ALTER TABLE intake_session_questions ADD CONSTRAINT fk_intake_session_questions_question_tenant FOREIGN KEY (organization_id,question_id) REFERENCES questionnaire_questions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_answers_session_tenant') THEN
    ALTER TABLE intake_answers ADD CONSTRAINT fk_intake_answers_session_tenant FOREIGN KEY (organization_id,session_id) REFERENCES intake_sessions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_answers_question_tenant') THEN
    ALTER TABLE intake_answers ADD CONSTRAINT fk_intake_answers_question_tenant FOREIGN KEY (organization_id,question_id) REFERENCES questionnaire_questions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_fact_conflicts_matter_tenant') THEN
    ALTER TABLE fact_conflicts ADD CONSTRAINT fk_fact_conflicts_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_fact_conflicts_resolution_tenant') THEN
    ALTER TABLE fact_conflicts ADD CONSTRAINT fk_fact_conflicts_resolution_tenant FOREIGN KEY (organization_id,resolution_fact_id) REFERENCES matter_facts(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_files_session_tenant') THEN
    ALTER TABLE intake_files ADD CONSTRAINT fk_intake_files_session_tenant FOREIGN KEY (organization_id,session_id) REFERENCES intake_sessions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_intake_files_question_tenant') THEN
    ALTER TABLE intake_files ADD CONSTRAINT fk_intake_files_question_tenant FOREIGN KEY (organization_id,question_id) REFERENCES questionnaire_questions(organization_id,id);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_stages_practice_tenant') THEN
    ALTER TABLE matter_stages ADD CONSTRAINT fk_matter_stages_practice_tenant FOREIGN KEY (organization_id,practice_area_id) REFERENCES practice_areas(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matters_practice_tenant') THEN
    ALTER TABLE matters ADD CONSTRAINT fk_matters_practice_tenant FOREIGN KEY (organization_id,practice_area_id) REFERENCES practice_areas(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matters_stage_tenant') THEN
    ALTER TABLE matters ADD CONSTRAINT fk_matters_stage_tenant FOREIGN KEY (organization_id,stage_id) REFERENCES matter_stages(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_participants_matter_tenant') THEN
    ALTER TABLE matter_participants ADD CONSTRAINT fk_matter_participants_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_participants_contact_tenant') THEN
    ALTER TABLE matter_participants ADD CONSTRAINT fk_matter_participants_contact_tenant FOREIGN KEY (organization_id,contact_id) REFERENCES contacts(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_field_groups_practice_tenant') THEN
    ALTER TABLE field_groups ADD CONSTRAINT fk_field_groups_practice_tenant FOREIGN KEY (organization_id,practice_area_id) REFERENCES practice_areas(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_field_definitions_group_tenant') THEN
    ALTER TABLE field_definitions ADD CONSTRAINT fk_field_definitions_group_tenant FOREIGN KEY (organization_id,group_id) REFERENCES field_groups(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_field_definitions_practice_tenant') THEN
    ALTER TABLE field_definitions ADD CONSTRAINT fk_field_definitions_practice_tenant FOREIGN KEY (organization_id,practice_area_id) REFERENCES practice_areas(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_field_values_matter_tenant') THEN
    ALTER TABLE matter_field_values ADD CONSTRAINT fk_matter_field_values_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_field_values_definition_tenant') THEN
    ALTER TABLE matter_field_values ADD CONSTRAINT fk_matter_field_values_definition_tenant FOREIGN KEY (organization_id,field_definition_id) REFERENCES field_definitions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_field_values_contact_tenant') THEN
    ALTER TABLE contact_field_values ADD CONSTRAINT fk_contact_field_values_contact_tenant FOREIGN KEY (organization_id,contact_id) REFERENCES contacts(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_field_values_definition_tenant') THEN
    ALTER TABLE contact_field_values ADD CONSTRAINT fk_contact_field_values_definition_tenant FOREIGN KEY (organization_id,field_definition_id) REFERENCES field_definitions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_sets_practice_tenant') THEN
    ALTER TABLE document_sets ADD CONSTRAINT fk_document_sets_practice_tenant FOREIGN KEY (organization_id,practice_area_id) REFERENCES practice_areas(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_set_versions_set_tenant') THEN
    ALTER TABLE document_set_versions ADD CONSTRAINT fk_document_set_versions_set_tenant FOREIGN KEY (organization_id,document_set_id) REFERENCES document_sets(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_set_items_version_tenant') THEN
    ALTER TABLE document_set_items ADD CONSTRAINT fk_document_set_items_version_tenant FOREIGN KEY (organization_id,version_id) REFERENCES document_set_versions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_set_items_template_tenant') THEN
    ALTER TABLE document_set_items ADD CONSTRAINT fk_document_set_items_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_set_items_template_version_tenant') THEN
    ALTER TABLE document_set_items ADD CONSTRAINT fk_document_set_items_template_version_tenant FOREIGN KEY (organization_id,template_version_id) REFERENCES template_versions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_set_drafts_set_tenant') THEN
    ALTER TABLE document_set_drafts ADD CONSTRAINT fk_document_set_drafts_set_tenant FOREIGN KEY (organization_id,document_set_id) REFERENCES document_sets(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_document_set_drafts_template_tenant') THEN
    ALTER TABLE document_set_drafts ADD CONSTRAINT fk_document_set_drafts_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_runs_matter_tenant') THEN
    ALTER TABLE generation_runs ADD CONSTRAINT fk_generation_runs_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_runs_set_version_tenant') THEN
    ALTER TABLE generation_runs ADD CONSTRAINT fk_generation_runs_set_version_tenant FOREIGN KEY (organization_id,document_set_version_id) REFERENCES document_set_versions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_outbox_events_matter_tenant') THEN
    ALTER TABLE outbox_events ADD CONSTRAINT fk_outbox_events_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_workflows_practice_tenant') THEN
    ALTER TABLE workflows ADD CONSTRAINT fk_workflows_practice_tenant FOREIGN KEY (organization_id,practice_area_id) REFERENCES practice_areas(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_public_workflow_session_tenant') THEN
    ALTER TABLE public_workflow_tokens ADD CONSTRAINT fk_public_workflow_session_tenant FOREIGN KEY (organization_id,session_id) REFERENCES workflow_sessions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_workflow_versions_workflow_tenant') THEN
    ALTER TABLE workflow_versions ADD CONSTRAINT fk_workflow_versions_workflow_tenant FOREIGN KEY (organization_id,workflow_id) REFERENCES workflows(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_workflow_sessions_version_tenant') THEN
    ALTER TABLE workflow_sessions ADD CONSTRAINT fk_workflow_sessions_version_tenant FOREIGN KEY (organization_id,workflow_version_id) REFERENCES workflow_versions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_workflow_sessions_matter_tenant') THEN
    ALTER TABLE workflow_sessions ADD CONSTRAINT fk_workflow_sessions_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_template_automation_drafts_template_tenant') THEN
    ALTER TABLE template_automation_drafts ADD CONSTRAINT fk_template_automation_drafts_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_template_automation_versions_template_tenant') THEN
    ALTER TABLE template_automation_versions ADD CONSTRAINT fk_template_automation_versions_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_template_automation_versions_snapshot_tenant') THEN
    ALTER TABLE template_automation_versions ADD CONSTRAINT fk_template_automation_versions_snapshot_tenant FOREIGN KEY (organization_id,template_version_id) REFERENCES template_versions(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_artifacts_matter_tenant') THEN
    ALTER TABLE generation_artifacts ADD CONSTRAINT fk_generation_artifacts_matter_tenant FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_artifacts_run_tenant') THEN
    ALTER TABLE generation_artifacts ADD CONSTRAINT fk_generation_artifacts_run_tenant FOREIGN KEY (organization_id,generation_run_id) REFERENCES generation_runs(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_artifacts_session_tenant') THEN
    ALTER TABLE generation_artifacts ADD CONSTRAINT fk_generation_artifacts_session_tenant FOREIGN KEY (organization_id,workflow_session_id) REFERENCES workflow_sessions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_artifacts_template_tenant') THEN
    ALTER TABLE generation_artifacts ADD CONSTRAINT fk_generation_artifacts_template_tenant FOREIGN KEY (organization_id,template_id) REFERENCES templates(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_artifacts_template_version_tenant') THEN
    ALTER TABLE generation_artifacts ADD CONSTRAINT fk_generation_artifacts_template_version_tenant FOREIGN KEY (organization_id,template_version_id) REFERENCES template_versions(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_runs_workflow_session_tenant') THEN
    ALTER TABLE generation_runs ADD CONSTRAINT fk_generation_runs_workflow_session_tenant FOREIGN KEY (organization_id,workflow_session_id) REFERENCES workflow_sessions(organization_id,id);
  END IF;
END $$;

-- Forced fail-closed RLS for every normal organization-owned table. Bootstrap
-- token-routing tables are deliberately excluded and must contain routing
-- metadata only.
DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'app_users','templates','template_versions','variables','activity_logs','intake_forms',
    'matters','matter_facts','matter_authorities','audit_events','matter_documents','document_bindings',
    'questionnaire_templates','questionnaire_versions','questionnaire_sections','questionnaire_questions',
    'intake_sessions','intake_session_questions','intake_answers','fact_conflicts','derived_fact_rules','intake_files',
    'organization_boilerplate','practice_areas','matter_stages','contacts','matter_participants','field_groups',
    'field_definitions','matter_field_values','contact_field_values','document_sets','document_set_versions',
    'document_set_items','document_set_drafts','generation_runs','outbox_events','workflows','workflow_versions',
    'workflow_sessions','template_automation_drafts','template_automation_versions','generation_artifacts'
  ] LOOP
    IF to_regclass(tbl) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
      EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
      EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I', tbl);
      EXECUTE format(
        'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id = autodraft_current_organization_id()) WITH CHECK (organization_id = autodraft_current_organization_id())',
        tbl
      );
    END IF;
  END LOOP;
END $$;

COMMENT ON TABLE app_users IS 'Organization-owned users protected by forced tenant RLS.';
COMMENT ON TABLE intake_forms IS 'Legacy intake forms remain tenant-owned and protected by forced tenant RLS.';
COMMENT ON TABLE audit_events IS 'Tenant-owned audit log protected by forced tenant RLS.';
