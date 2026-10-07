from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import Database
from ..token_security import bearer_token_hash


class IntakeRepository:
    def __init__(self, db: Database): self.db=db

    async def list_templates(self):
        return await self.db.p().fetch(
            """SELECT qt.id,qt.title,qt.matter_type,qt.status,qt.created_at,qt.updated_at,
                      COALESCE(MAX(qv.version_number),0) AS latest_version,
                      MAX(qv.published_at) AS published_at
               FROM questionnaire_templates qt LEFT JOIN questionnaire_versions qv ON qv.template_id=qt.id
               GROUP BY qt.id ORDER BY qt.updated_at DESC"""
        )

    async def get_template(self, qid: uuid.UUID):
        return await self.db.p().fetchrow("SELECT id,title,matter_type,status,created_at,updated_at FROM questionnaire_templates WHERE id=$1",qid)

    async def latest_version(self, qid: uuid.UUID, *, published_only: bool=False):
        where="AND status='published'" if published_only else ""
        return await self.db.p().fetchrow(f"SELECT id,version_number,status,created_at,published_at FROM questionnaire_versions WHERE template_id=$1 {where} ORDER BY version_number DESC LIMIT 1",qid)

    async def version_sections(self, version_id: uuid.UUID):
        return await self.db.p().fetch("SELECT id,title,description,position FROM questionnaire_sections WHERE version_id=$1 ORDER BY position,id",version_id)

    async def version_questions(self, version_id: uuid.UUID):
        return await self.db.p().fetch("""SELECT id,section_id,position,label,help_text,question_type,required,fact_key,options,display_rule,validation,approved
                                          FROM questionnaire_questions WHERE version_id=$1 ORDER BY position,id""",version_id)

    async def save_definition(self, *, questionnaire_id: uuid.UUID|None, title:str, matter_type:str, sections:list[dict[str,Any]], questions:list[dict[str,Any]]):
        async with self.db.p().transaction() as conn:
            if questionnaire_id is None:
                questionnaire_id=uuid.uuid4()
                await conn.execute("INSERT INTO questionnaire_templates(organization_id,id,title,matter_type,status) VALUES(autodraft_current_organization_id(),$1,$2,$3,'draft')",questionnaire_id,title,matter_type)
                version_number=1; version_id=uuid.uuid4()
                await conn.execute("INSERT INTO questionnaire_versions(id,template_id,version_number,status) VALUES($1,$2,$3,'draft')",version_id,questionnaire_id,version_number)
            else:
                template=await conn.fetchrow("SELECT id FROM questionnaire_templates WHERE id=$1",questionnaire_id)
                if not template:return None
                latest=await conn.fetchrow("SELECT id,version_number,status FROM questionnaire_versions WHERE template_id=$1 ORDER BY version_number DESC LIMIT 1 FOR UPDATE",questionnaire_id)
                if latest and latest['status']=='draft':
                    version_id=latest['id'];version_number=latest['version_number']
                    await conn.execute("DELETE FROM questionnaire_sections WHERE version_id=$1",version_id)
                    await conn.execute("DELETE FROM questionnaire_questions WHERE version_id=$1",version_id)
                else:
                    version_number=int(latest['version_number'] if latest else 0)+1;version_id=uuid.uuid4()
                    await conn.execute("INSERT INTO questionnaire_versions(id,template_id,version_number,status) VALUES($1,$2,$3,'draft')",version_id,questionnaire_id,version_number)
                await conn.execute("UPDATE questionnaire_templates SET title=$1,matter_type=$2,status='draft',updated_at=NOW() WHERE id=$3",title,matter_type,questionnaire_id)

            section_map:dict[str,uuid.UUID]={}
            for index,section in enumerate(sections):
                original=str(section.get('id') or '')
                try:sid=uuid.UUID(original)
                except Exception:sid=uuid.uuid4()
                section_map[original]=sid
                await conn.execute("INSERT INTO questionnaire_sections(id,version_id,title,description,position) VALUES($1,$2,$3,$4,$5)",sid,version_id,str(section.get('title') or 'Questions'),str(section.get('description') or ''),int(section.get('position',index)))
            if not sections:
                sid=uuid.uuid4();section_map['default']=sid
                await conn.execute("INSERT INTO questionnaire_sections(id,version_id,title,description,position) VALUES($1,$2,'Questions','',0)",sid,version_id)

            question_id_map:dict[str,uuid.UUID]={}
            for question in questions:
                original=str(question.get('id') or '')
                try:qid=uuid.UUID(original)
                except Exception:qid=uuid.uuid4()
                question_id_map[original]=qid
            for index,question in enumerate(questions):
                original=str(question.get('id') or '')
                qid=question_id_map[original]
                section_key=str(question.get('sectionId') or question.get('section_id') or ('default' if not sections else sections[0].get('id','')))
                sid=section_map.get(section_key) or next(iter(section_map.values()))
                rule=question.get('displayRule') or question.get('display_rule')
                if isinstance(rule,dict) and rule.get('questionId') in question_id_map:
                    rule={**rule,'questionId':str(question_id_map[rule['questionId']])}
                await conn.execute("""INSERT INTO questionnaire_questions(id,version_id,section_id,position,label,help_text,question_type,required,fact_key,options,display_rule,validation,approved)
                                      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12::jsonb,$13)""",
                                   qid,version_id,sid,int(question.get('position',index)),str(question.get('label') or ''),str(question.get('helpText') or question.get('help_text') or ''),str(question.get('type') or question.get('question_type') or 'text'),bool(question.get('required')),str(question.get('mapsTo') or question.get('fact_key') or '') or None,list(question.get('options') or []),rule,dict(question.get('validation') or {}),bool(question.get('approved',True)))
        return questionnaire_id,version_id,version_number

    async def publish(self, qid:uuid.UUID):
        async with self.db.p().transaction() as conn:
            latest=await conn.fetchrow("SELECT id,version_number,status FROM questionnaire_versions WHERE template_id=$1 ORDER BY version_number DESC LIMIT 1 FOR UPDATE",qid)
            if not latest:return None
            unapproved=await conn.fetchval("SELECT COUNT(*) FROM questionnaire_questions WHERE version_id=$1 AND approved=FALSE",latest['id'])
            if unapproved:return {"unapproved":int(unapproved)}
            count=await conn.fetchval("SELECT COUNT(*) FROM questionnaire_questions WHERE version_id=$1",latest['id'])
            if not count:return {"empty":True}
            await conn.execute("UPDATE questionnaire_versions SET status='retired' WHERE template_id=$1 AND status='published'",qid)
            await conn.execute("UPDATE questionnaire_versions SET status='published',published_at=NOW() WHERE id=$1",latest['id'])
            await conn.execute("UPDATE questionnaire_templates SET status='published',updated_at=NOW() WHERE id=$1",qid)
            return {"versionId":str(latest['id']),"version":latest['version_number']}

    async def create_session(self, qid:uuid.UUID, *, token:str, matter_id:uuid.UUID|None, expires_at):
        version=await self.latest_version(qid,published_only=True)
        if not version:return None
        async with self.db.p().transaction() as conn:
            token_hash=bearer_token_hash(token)
            session=await conn.fetchrow("INSERT INTO intake_sessions(organization_id,questionnaire_version_id,matter_id,token_hash,expires_at) VALUES(autodraft_current_organization_id(),$1,$2,$3,$4) RETURNING id,organization_id,created_at",version['id'],matter_id,token_hash,expires_at)
            await conn.execute("INSERT INTO public_intake_token_hashes(token_hash,organization_id,session_id) VALUES($1,$2,$3) ON CONFLICT(token_hash) DO UPDATE SET organization_id=EXCLUDED.organization_id,session_id=EXCLUDED.session_id",token_hash,session['organization_id'],session['id'])
            questions=await conn.fetch("""SELECT q.id,q.section_id,q.position,q.label,q.help_text,q.question_type,q.required,q.fact_key,q.options,q.display_rule,q.validation,q.approved,
                                           s.title AS section_title,s.description AS section_description,s.position AS section_position
                                    FROM questionnaire_questions q LEFT JOIN questionnaire_sections s ON s.id=q.section_id
                                    WHERE q.version_id=$1 ORDER BY COALESCE(s.position,0),q.position,q.id""",version['id'])
            for q in questions:
                snapshot={"id":str(q['id']),"sectionId":str(q['section_id']) if q['section_id'] else None,"sectionTitle":q['section_title'] or 'Questions',"sectionDescription":q['section_description'] or '',"sectionPosition":q['section_position'] or 0,"position":q['position'],"label":q['label'],"helpText":q['help_text'],"type":q['question_type'],"required":q['required'],"mapsTo":q['fact_key'] or '',"options":q['options'] or [],"displayRule":q['display_rule'],"validation":q['validation'] or {},"approved":q['approved']}
                await conn.execute("INSERT INTO intake_session_questions(session_id,question_id,snapshot,position) VALUES($1,$2,$3::jsonb,$4)",session['id'],q['id'],snapshot,q['position'])
        return session,version

    async def session_files(self, session_id: uuid.UUID):
        return await self.db.p().fetch(
            """SELECT id,question_id,filename,mime_type,declared_mime,detected_mime,scan_status,scan_engine,size_bytes,sha256,created_at
               FROM intake_files WHERE session_id=$1 ORDER BY created_at DESC,id DESC""",
            session_id,
        )

    async def session_file(self, session_id: uuid.UUID, question_id: uuid.UUID):
        return await self.db.p().fetchrow(
            """SELECT id,question_id,filename,mime_type,declared_mime,detected_mime,scan_status,scan_engine,size_bytes,sha256,content,created_at
               FROM intake_files WHERE session_id=$1 AND question_id=$2
               ORDER BY created_at DESC,id DESC LIMIT 1""",
            session_id, question_id,
        )

    async def session_by_token(self, token:str):
        token_hash=bearer_token_hash(token)
        return await self.db.p().fetchrow("""SELECT s.id,s.status,s.matter_id,s.questionnaire_version_id,s.created_at,s.expires_at,s.submitted_at,s.revoked_at,qt.title,qt.matter_type,qv.version_number
                                            FROM intake_sessions s JOIN questionnaire_versions qv ON qv.id=s.questionnaire_version_id JOIN questionnaire_templates qt ON qt.id=qv.template_id
                                            WHERE s.token_hash=$1""",token_hash)

    async def legacy_public_organization_by_token(self, token: str):
        """Resolve only the tenant routing metadata for a legacy public intake token."""
        async with self.db.raw_pool().acquire() as conn:
            return await conn.fetchval(
                "SELECT organization_id FROM public_legacy_intake_token_hashes WHERE token_hash=$1", bearer_token_hash(token)
            )

    async def public_session_by_token(self, token:str):
        """Resolve a bearer intake token before a tenant context exists.

        The lookup table is deliberately not tenant-RLS protected; it contains
        only the unguessable token and the tenant/session IDs needed to establish
        the correct RLS GUC. The protected session is then read inside a
        transaction scoped to that organization.
        """
        async with self.db.raw_pool().acquire() as conn:
            token_hash=bearer_token_hash(token)
            lookup=await conn.fetchrow("SELECT organization_id,session_id FROM public_intake_token_hashes WHERE token_hash=$1",token_hash)
            if not lookup:return None
            async with conn.transaction():
                await conn.execute("SELECT set_config('autodraft.organization_id',$1,true)",str(lookup['organization_id']))
                return await conn.fetchrow("""SELECT s.id,s.organization_id,s.status,s.matter_id,s.questionnaire_version_id,s.created_at,s.expires_at,s.submitted_at,s.revoked_at,qt.title,qt.matter_type,qv.version_number
                                              FROM intake_sessions s JOIN questionnaire_versions qv ON qv.id=s.questionnaire_version_id JOIN questionnaire_templates qt ON qt.id=qv.template_id
                                              WHERE s.id=$1 AND s.token_hash=$2""",lookup['session_id'],token_hash)

    async def session_questions(self, session_id:uuid.UUID):
        return await self.db.p().fetch("SELECT question_id,snapshot,position FROM intake_session_questions WHERE session_id=$1 ORDER BY position,id",session_id)

    async def answers(self, session_id:uuid.UUID):
        return await self.db.p().fetch("SELECT question_id,answer_text,answer_json,review_status,created_at,reviewed_at FROM intake_answers WHERE session_id=$1 ORDER BY created_at",session_id)
