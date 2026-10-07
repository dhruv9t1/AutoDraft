from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from ..ocr_service import OcrService, dependency_status, ocr_smoke_status
from ..runtime import api_auth, runtime_state, settings, utc_iso
from ..storage import safe_filename

router = APIRouter(tags=["ocr"])


def _public_ocr_job(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    payload = {
        "jobId": job_id,
        "status": job.get("status", "queued"),
        "error": job.get("error"),
        "filename": job.get("input_filename"),
        "pages": result.get("pages"),
        "ocrPerformed": result.get("ocrPerformed"),
        "hadCompleteTextLayer": result.get("hadCompleteTextLayer"),
        "languages": result.get("languages", settings.ocr_language_list),
        "extractedCharacters": result.get("extractedCharacters", 0),
        "createdAt": utc_iso(job.get("created_at")),
        "attemptCount": int(job.get("attempt_count") or 0),
    }
    if job.get("status") == "completed":
        payload["text"] = result.get("text", "")
    return payload


@router.get("/api/ocr/status",dependencies=[Depends(api_auth)])
async def ocr_status(forceSmoke: bool = False):
    required=tuple(settings.ocr_language_list)
    state=await dependency_status(required)
    smoke=await ocr_smoke_status(required, force=forceSmoke)
    return {
        "ready":bool(state.ready and smoke.passed),
        "dependencyReady":state.ready,
        "ocrmypdf":state.ocrmypdf,"tesseract":state.tesseract,
        "installedLanguages":list(state.installed_languages),"missingLanguages":list(state.missing_languages),
        "requiredLanguages":settings.ocr_language_list,
        "smokeTest":{
            "passed":smoke.passed,
            "checkedAt":smoke.checked_at,
            "message":smoke.message,
            "recognisedCharacters":smoke.recognised_characters,
        },
    }


@router.post("/api/ocr/jobs",dependencies=[Depends(api_auth)])
async def create_ocr_job(request: Request, file: UploadFile = File(...)):
    filename=safe_filename((file.filename or "upload").strip() or "upload","upload")
    suffix=Path(filename).suffix.lower()
    if suffix not in OcrService.SUPPORTED_SUFFIXES:
        raise HTTPException(415,"Unsupported OCR input. Use PDF, JPG, JPEG, PNG, TIFF or TIF.")
    data=bytearray()
    try:
        while True:
            chunk=await file.read(1024*1024)
            if not chunk: break
            data.extend(chunk)
            if len(data) > settings.ocr_max_upload_bytes:
                raise HTTPException(413,"OCR upload is too large")
    finally:
        await file.close()
    job=await runtime_state.create_job(
        "ocr",
        owner_user_id=request.state.security.user_id,
        payload={},
        input_blob=bytes(data),
        input_filename=filename,
        input_suffix=suffix,
        ttl_seconds=settings.ocr_job_ttl_seconds,
    )
    return _public_ocr_job(str(job["id"]), job)


@router.get("/api/ocr/jobs/{job_id}",dependencies=[Depends(api_auth)])
async def get_ocr_job(job_id: str, request: Request):
    job=await runtime_state.get_job(job_id,owner_user_id=request.state.security.user_id)
    if not job or job.get("job_type") != "ocr": raise HTTPException(404,"OCR job not found")
    return _public_ocr_job(job_id, job)


@router.get("/api/ocr/jobs/{job_id}/searchable-pdf",dependencies=[Depends(api_auth)])
async def download_ocr_pdf(job_id: str, request: Request):
    job=await runtime_state.get_job(job_id,owner_user_id=request.state.security.user_id,include_blob=True)
    if not job or job.get("job_type") != "ocr": raise HTTPException(404,"OCR job not found")
    if job.get("status")!="completed" or not job.get("output_blob"):
        raise HTTPException(409,"OCR job has not completed")
    stem=Path(job.get("input_filename") or "document").stem
    filename=safe_filename(f"{stem}-searchable.pdf","document-searchable.pdf")
    return Response(
        content=bytes(job["output_blob"]),
        media_type="application/pdf",
        headers={"Content-Disposition":f'attachment; filename="{filename}"'},
    )


@router.delete("/api/ocr/jobs/{job_id}",status_code=204,dependencies=[Depends(api_auth)])
async def delete_ocr_job(job_id: str, request: Request):
    await runtime_state.request_cancel(job_id,owner_user_id=request.state.security.user_id)
    return Response(status_code=204)
