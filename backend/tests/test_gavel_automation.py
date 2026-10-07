from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.domain.expressions import ExpressionError, evaluate, evaluate_bool
from app.domain.template_automation import preflight_blueprint, render_docx, validate_blueprint
from app.domain.workflows import WorkflowDefinitionError, evaluate_workflow, validate_workflow_definition

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
MIGRATION=(ROOT/'migrations'/'20261005000016_gavel_automation.sql').read_text()
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _sdt(tag:str,text:str) -> str:
    return f'''<w:sdt><w:sdtPr><w:tag w:val="{tag}"/></w:sdtPr><w:sdtContent><w:r><w:t>{text}</w:t></w:r></w:sdtContent></w:sdt>'''


def _docx(xml:str) -> bytes:
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml',xml)
    return buf.getvalue()


def _text(docx:bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        root=ET.fromstring(z.read('word/document.xml'))
    return ''.join((x.text or '') for x in root.findall(f'.//{{{W}}}t'))


def test_expression_engine_supports_gavel_style_logic_without_eval():
    data={'amount':30000,'kind':'company','start':'2026-01-01','children':[{'name':'A'},{'name':'B'}]}
    assert evaluate_bool({'and':[{'gt':[{'field':'amount'},{'literal':10000}]},{'eq':[{'field':'kind'},{'literal':'company'}]}]},data)
    assert evaluate({'date_add':[{'field':'start'},{'literal':30}]},data).value=='2026-01-31'
    assert evaluate({'format_number':[{'field':'amount'}],'decimals':2,'grouping':True,'symbol':'₹'},data).value=='₹30,000.00'
    assert evaluate({'item':'name'},data,item={'name':'Child'}).value=='Child'
    with pytest.raises(ExpressionError):evaluate({'op':'__import__','args':[]},data)


def test_workflow_calculations_conditions_and_nested_repeaters():
    definition={
      'calculations':[{'key':'claim.total','expression':{'add':[{'field':'principal'},{'field':'interest'}]}}],
      'pages':[{'id':'claim','title':'Claim','condition':{'gte':[{'var':'claim.total'},{'literal':100}]} ,'questions':[
        {'id':'client','label':'Client','semanticKey':'client.name','required':True},
        {'id':'children','label':'Children','semanticKey':'children','type':'repeater','required':True,'minItems':1,'children':[
          {'id':'child_name','label':'Child name','semanticKey':'name','required':True},
          {'id':'assets','label':'Assets','semanticKey':'assets','type':'repeater','children':[
            {'id':'asset_name','label':'Asset','semanticKey':'name','required':True}
          ]}
        ]}
      ]}]
    }
    good={'principal':90,'interest':20,'client.name':'Asha','children':[{'name':'Riya','assets':[{'name':'Flat'}]}]}
    result=evaluate_workflow(definition,good)
    assert result.complete is True
    assert result.calculations['claim.total']==110
    bad={**good,'children':[{'name':'','assets':[{}]}]}
    result=evaluate_workflow(definition,bad)
    assert result.complete is False
    paths={x['path'] for x in result.missing_required}
    assert 'children[0].' in paths
    assert 'children[0].assets[0].' in paths


def test_workflow_definition_rejects_duplicate_ids_and_unsafe_expression():
    with pytest.raises(WorkflowDefinitionError):
        validate_workflow_definition({'pages':[{'id':'p','questions':[{'id':'q','label':'A','semanticKey':'a'},{'id':'q','label':'B','semanticKey':'b'}]}],'calculations':[]})
    with pytest.raises(WorkflowDefinitionError):
        validate_workflow_definition({'pages':[],'calculations':[{'key':'x','expression':{'op':'eval','args':[]}}]})


def test_template_preflight_and_headless_renderer_cover_conditions_and_nested_repeaters():
    document=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{W}"><w:body>
      <w:p>{_sdt('field-client','CLIENT')}</w:p>
      <w:sdt><w:sdtPr><w:tag w:val="autodraft:condition:c1"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>COMPANY CLAUSE</w:t></w:r></w:p></w:sdtContent></w:sdt>
      <w:sdt><w:sdtPr><w:tag w:val="autodraft:repeat:r1"/></w:sdtPr><w:sdtContent>
        <w:p><w:r><w:t>Child: </w:t></w:r>{_sdt('field-child','NAME')}</w:p>
        <w:sdt><w:sdtPr><w:tag w:val="autodraft:repeat:r2"/></w:sdtPr><w:sdtContent>
          <w:p><w:r><w:t>Asset: </w:t></w:r>{_sdt('field-asset','ASSET')}</w:p>
        </w:sdtContent></w:sdt>
      </w:sdtContent></w:sdt>
    </w:body></w:document>'''
    content=_docx(document)
    blueprint={
      'bindings':[
        {'controlTag':'field-client','semanticKey':'client.name'},
        {'controlTag':'field-child','expression':{'item':'name'}},
        {'controlTag':'field-asset','expression':{'item':'name'}},
      ],
      'conditions':[{'regionTag':'autodraft:condition:c1','expression':{'eq':[{'field':'party.type'},{'literal':'company'}]}}],
      'repeaters':[
        {'regionTag':'autodraft:repeat:r1','collectionKey':'children'},
        {'regionTag':'autodraft:repeat:r2','collectionExpression':{'item':'assets'}},
      ]
    }
    assert preflight_blueprint(blueprint,content)['ready'] is True
    rendered=render_docx(content,blueprint,{'client.name':'Asha','party.type':'individual','children':[{'name':'Riya','assets':[{'name':'Flat'},{'name':'Deposit'}]},{'name':'Neel','assets':[]}]})
    text=_text(rendered.content)
    assert 'Asha' in text and 'Riya' in text and 'Neel' in text
    assert 'Flat' in text and 'Deposit' in text
    assert 'COMPANY CLAUSE' not in text
    assert rendered.stats['repeatedItems']==4  # 2 children + 2 nested assets
    missing=preflight_blueprint({**blueprint,'conditions':[{'regionTag':'missing','expression':{'literal':True}}]},content)
    assert missing['ready'] is False
    assert any(x['code']=='MISSING_CONDITION_REGION' for x in missing['issues'])


def test_gavel_migration_has_versioned_workflows_automation_and_rls():
    for table in ('workflows','workflow_versions','workflow_sessions','public_workflow_tokens','template_automation_drafts','template_automation_versions','generation_artifacts'):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in MIGRATION
    for tenant_table in ('workflows','workflow_versions','workflow_sessions','template_automation_drafts','template_automation_versions','generation_artifacts'):
        assert f"'{tenant_table}'" in MIGRATION
    assert 'ENABLE ROW LEVEL SECURITY' in MIGRATION
    assert 'workflow_session_id' in MIGRATION and 'artifact_ids' in MIGRATION


def test_workflow_versions_are_immutable_after_publish_and_public_tokens_are_hashed():
    source=(ROOT/'app'/'repositories'/'workflows.py').read_text()
    assert "latest['status']=='draft'" in source
    assert "status='retired'" in source
    assert 'hashlib.sha256(token.encode()).hexdigest()' in source
    assert 'public_workflow_tokens' in source
    assert 'token_hash' in source


def test_template_automation_is_pinned_to_template_version_and_preflight_blocks_publish():
    source=(ROOT/'app'/'repositories'/'automation.py').read_text()
    assert 'template_version_id' in source
    assert 'Template automation preflight failed' in source
    assert 'immutable template version already has a different published automation blueprint' in source


def test_headless_generation_requires_published_blueprint_and_writes_artifact():
    source=(ROOT/'app'/'services'/'generation_service.py').read_text()
    assert 'has no published automation blueprint' in source
    assert 'INSERT INTO generation_artifacts' in source
    assert 'DocumentGenerated' in source
    assert "source,'automation'" not in source  # SQL parameter remains explicit/typed; avoid source-string injection.


def test_word_ui_exposes_workflows_conditions_repeaters_preflight_and_headless_generation():
    panel=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'AutomationPanel.tsx').read_text()
    workspace=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'DraftingWorkspace.tsx').read_text()
    region=(PROJECT/'word-extension'/'src'/'services'/'word'/'automationRegionService.ts').read_text()
    for token in ('Workflow builder','Wrap selected Word region as condition','Wrap selected Word region as repeater','Preflight','Headless generate DOCX'):
        assert token in panel
    assert '<AutomationPanel' in workspace
    assert 'runWordOperation' in region and 'autodraft:${kind}:' in region


def test_main_wires_gavel_routers_and_public_workflow_bypasses_api_auth_only_for_token_routes():
    main=(ROOT/'app'/'main.py').read_text();workflows=(ROOT/'app'/'api'/'workflows.py').read_text()
    assert 'workflows_router' in main and 'automation_router' in main
    assert 'path.startswith("/api/workflows/public/")' in main
    assert "@router.get('/workflow/{token}'" in workflows
    assert 'version="1.3.0"' in main


def test_completed_workflow_data_requires_explicit_lawyer_promotion_to_existing_fields():
    source=(ROOT/'app'/'api'/'workflows.py').read_text()
    assert "@router.post('/api/workflow-sessions/{session_id}/apply-to-matter'" in source
    assert "Workflow session must be completed before applying data" in source
    assert "field_repo.definitions(scope='matter',include_inactive=False)" in source
    assert "No active matter field definition" in source
    assert "source='workflow',status='confirmed'" in source
    # Public completion must not silently call the canonical-field repository.
    public_block=source.split("@router.post('/api/workflows/public/{token}/complete')",1)[1].split("@router.get('/workflow/{token}'",1)[0]
    assert 'field_repo.upsert_matter_value' not in public_block


def test_generation_rejects_cross_matter_and_cross_set_combinations():
    source=(ROOT/'app'/'services'/'generation_service.py').read_text()
    for message in (
        'Generation run belongs to a different document set version',
        'Generation run belongs to a different matter',
        'Workflow session belongs to a different matter',
        'Generation run is pinned to a document set; do not supply templateId',
    ):
        assert message in source
    assert 'size_bytes' in source and 'len(rendered.content)' in source


def test_blueprint_editor_keeps_raw_json_text_until_validation():
    panel=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'AutomationPanel.tsx').read_text()
    assert 'blueprintText' in panel
    assert 'setBlueprintText(d.value)' in panel
    assert 'const parseBlueprint=()' in panel
    assert 'try{setBlueprint(JSON.parse(d.value));}catch{}' not in panel
    assert 'Apply completed session to matter' in panel


def test_v13_product_versions_are_consistent():
    import json
    pkg=json.loads((PROJECT/'word-extension'/'package.json').read_text())
    lock_path=PROJECT/'word-extension'/'package-lock.json'
    lock=json.loads(lock_path.read_text()) if lock_path.exists() else None
    manifest=(PROJECT/'word-extension'/'manifest.xml').read_text()
    pyproject=(ROOT/'pyproject.toml').read_text()
    main=(ROOT/'app'/'main.py').read_text()
    assert pkg['version']=='1.3.0'
    if lock is not None:
        assert lock['version']=='1.3.0' and lock['packages']['']['version']=='1.3.0'
    else:
        prepare=(PROJECT/'scripts'/'prepare-production-candidate.sh').read_text()
        assert 'npm install --package-lock-only --ignore-scripts' in prepare
    assert '<Version>1.3.0.0</Version>' in manifest
    assert 'version = "1.3.0"' in pyproject
    assert 'version="1.3.0"' in main


def test_expression_branching_short_circuits_inactive_runtime_errors():
    dangerous={'divide':[{'literal':1},{'literal':0}]}
    assert evaluate({'if':[{'literal':False},dangerous,{'literal':'safe'}]},{}).value=='safe'
    assert evaluate({'and':[{'literal':False},dangerous]},{}).value is False
    assert evaluate({'or':[{'literal':True},dangerous]},{}).value is True
    assert evaluate({'coalesce':[{'literal':'first'},dangerous]},{}).value=='first'
    with pytest.raises(ExpressionError):
        evaluate({'format_number':[{'literal':10}],'decimals':100},{}).value


def test_document_set_population_ui_calls_headless_generator_before_review():
    panel=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'LegalDataPanel.tsx').read_text()
    assert 'generateHeadless' in panel
    assert 'generationRunId:generationRun.id' in panel
    assert 'Generate document set → Review' in panel
    assert 'generatedArtifacts:result.artifacts.map' in panel
