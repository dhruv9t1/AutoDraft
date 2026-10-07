from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
import time
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader

from .config import get_settings

try:  # POSIX resource limits are available on Linux/macOS production hosts.
    import resource
except ImportError:  # pragma: no cover - Windows fallback remains timeout/monitor based.
    resource = None  # type: ignore[assignment]


class OcrDependencyError(RuntimeError):
    pass


class OcrProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrDependencyStatus:
    ocrmypdf: bool
    tesseract: bool
    installed_languages: tuple[str, ...]
    missing_languages: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.ocrmypdf and self.tesseract and not self.missing_languages


@dataclass(frozen=True)
class OcrSmokeStatus:
    passed: bool
    checked_at: float
    message: str
    recognised_characters: int = 0


@dataclass(frozen=True)
class OcrResult:
    searchable_pdf: Path
    sidecar_text: Path | None
    extracted_text: Path
    text: str
    languages: tuple[str, ...]
    pages: int
    had_complete_text_layer: bool
    ocr_performed: bool


def _directory_size(path: Path) -> int:
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _build_resource_preexec():
    if resource is None:
        return None
    settings = get_settings()
    limits = (
        ("RLIMIT_AS", int(settings.ocr_subprocess_max_memory_bytes)),
        ("RLIMIT_CPU", int(settings.ocr_subprocess_max_cpu_seconds)),
        ("RLIMIT_FSIZE", int(settings.ocr_subprocess_max_file_bytes)),
    )

    def apply_limits() -> None:
        for name, value in limits:
            if value <= 0 or not hasattr(resource, name):
                continue
            which = getattr(resource, name)
            _soft, hard = resource.getrlimit(which)
            target = value if hard == resource.RLIM_INFINITY else min(value, int(hard))
            resource.setrlimit(which, (target, target))

    return apply_limits


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - Windows fallback
            process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
        return
    except TimeoutError:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
    except ProcessLookupError:
        return
    await process.wait()


async def _run(
    *args: str,
    timeout: float | None = None,
    resource_limited: bool = False,
    temp_dir: Path | None = None,
    monitor_dir: Path | None = None,
) -> tuple[int, str, str]:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    env = os.environ.copy()
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        env["TEMP"] = str(temp_dir)
        kwargs["env"] = env
    if os.name == "posix":
        kwargs["start_new_session"] = True
        if resource_limited and resource is not None:
            preexec = _build_resource_preexec()
            if preexec is not None:
                kwargs["preexec_fn"] = preexec

    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    communicate = asyncio.create_task(process.communicate())
    started = asyncio.get_running_loop().time()
    try:
        while True:
            elapsed = asyncio.get_running_loop().time() - started
            if timeout is not None and elapsed >= timeout:
                await _terminate_process(process)
                raise OcrProcessingError("OCR timed out before completion.")
            wait_for = 0.5 if timeout is None else max(0.05, min(0.5, timeout - elapsed))
            done, _ = await asyncio.wait({communicate}, timeout=wait_for)
            if done:
                stdout, stderr = communicate.result()
                break
            watched = monitor_dir or temp_dir
            if resource_limited and watched is not None and settings.ocr_max_temp_bytes > 0:
                size = await asyncio.to_thread(_directory_size, watched)
                if size > settings.ocr_max_temp_bytes:
                    await _terminate_process(process)
                    raise OcrProcessingError(
                        f"OCR temporary files exceeded the configured limit ({settings.ocr_max_temp_bytes} bytes)."
                    )
    except asyncio.CancelledError:
        await _terminate_process(process)
        communicate.cancel()
        raise
    except BaseException:
        if process.returncode is None:
            await _terminate_process(process)
        if not communicate.done():
            communicate.cancel()
        raise
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


async def installed_tesseract_languages() -> set[str]:
    if not shutil.which("tesseract"):
        raise OcrDependencyError(
            "Tesseract is not installed. On macOS run: brew install ocrmypdf"
        )
    code, stdout, stderr = await _run("tesseract", "--list-langs", timeout=30)
    if code != 0:
        raise OcrDependencyError(f"Could not read Tesseract languages: {stderr.strip()}")
    return {
        line.strip()
        for line in stdout.splitlines()
        if line.strip() and "List of available languages" not in line
    }


async def dependency_status(required: tuple[str, ...] = ("guj", "eng")) -> OcrDependencyStatus:
    has_ocr = bool(shutil.which("ocrmypdf"))
    has_tess = bool(shutil.which("tesseract"))
    installed: set[str] = set()
    if has_tess:
        try:
            installed = await installed_tesseract_languages()
        except OcrDependencyError:
            installed = set()
    missing = tuple(lang for lang in required if lang not in installed)
    return OcrDependencyStatus(
        ocrmypdf=has_ocr,
        tesseract=has_tess,
        installed_languages=tuple(sorted(installed)),
        missing_languages=missing,
    )


async def ensure_ocr_dependencies(required: tuple[str, ...] = ("guj", "eng")) -> None:
    status = await dependency_status(required)
    if not status.ocrmypdf:
        raise OcrDependencyError(
            "OCRmyPDF is not installed. On macOS run: brew install ocrmypdf"
        )
    if not status.tesseract:
        raise OcrDependencyError(
            "Tesseract is not installed. On macOS run: brew install ocrmypdf"
        )
    if status.missing_languages:
        raise OcrDependencyError(
            "Missing Tesseract OCR language pack(s): "
            + ", ".join(status.missing_languages)
            + ". On macOS run: brew install tesseract-lang"
        )


def _validated_pdf_reader(path: Path) -> PdfReader:
    settings = get_settings()
    try:
        reader = PdfReader(str(path), strict=False)
    except Exception as exc:
        raise OcrProcessingError("PDF could not be parsed safely.") from exc
    if reader.is_encrypted:
        raise OcrProcessingError("Encrypted PDFs are not supported for OCR.")
    try:
        pages = len(reader.pages)
    except Exception as exc:
        raise OcrProcessingError("PDF page tree could not be read safely.") from exc
    if pages <= 0:
        raise OcrProcessingError("PDF contains no pages.")
    if pages > settings.ocr_max_pdf_pages:
        raise OcrProcessingError(
            f"PDF contains too many pages ({pages} > {settings.ocr_max_pdf_pages})."
        )
    for index, page in enumerate(reader.pages, start=1):
        try:
            user_unit = float(page.get("/UserUnit", 1) or 1)
            width = abs(float(page.mediabox.width)) * user_unit
            height = abs(float(page.mediabox.height)) * user_unit
        except Exception as exc:
            raise OcrProcessingError(f"PDF page {index} has invalid dimensions.") from exc
        if width <= 0 or height <= 0:
            raise OcrProcessingError(f"PDF page {index} has non-positive dimensions.")
        if width > settings.ocr_max_pdf_page_width_points or height > settings.ocr_max_pdf_page_height_points:
            raise OcrProcessingError(
                f"PDF page {index} dimensions exceed the configured OCR limit ({width:.1f}x{height:.1f} points)."
            )
        if width * height > settings.ocr_max_pdf_page_area_points:
            raise OcrProcessingError(
                f"PDF page {index} area exceeds the configured OCR limit."
            )
    return reader


def _extract_pdf_text(path: Path) -> tuple[str, int, bool]:
    settings = get_settings()
    reader = _validated_pdf_reader(path)
    chunks: list[str] = []
    page_has_text: list[bool] = []
    total_chars = 0
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise OcrProcessingError("PDF text extraction failed safely.") from exc
        total_chars += len(text)
        if total_chars > settings.ocr_max_extracted_text_chars:
            raise OcrProcessingError("Extracted PDF text exceeds the configured character limit.")
        chunks.append(text)
        page_has_text.append(bool(text.strip()))
    return "\n\n".join(chunks).strip(), len(reader.pages), bool(page_has_text) and all(page_has_text)


def _validate_image_limits(image: Image.Image) -> None:
    settings = get_settings()
    try:
        frame_count = int(getattr(image, "n_frames", 1) or 1)
    except Exception as exc:
        raise OcrProcessingError("Image frame metadata could not be read safely.") from exc
    if frame_count <= 0 or frame_count > settings.ocr_max_image_frames:
        raise OcrProcessingError(
            f"Image has too many frames ({frame_count} > {settings.ocr_max_image_frames})."
        )
    total_pixels = 0
    for idx in range(frame_count):
        try:
            image.seek(idx)
            width, height = image.size
        except Exception as exc:
            raise OcrProcessingError(f"Image frame {idx + 1} could not be inspected safely.") from exc
        if width <= 0 or height <= 0:
            raise OcrProcessingError(f"Image frame {idx + 1} has invalid dimensions.")
        if width > settings.ocr_max_image_width or height > settings.ocr_max_image_height:
            raise OcrProcessingError(
                f"Image frame {idx + 1} dimensions exceed the configured OCR limit ({width}x{height})."
            )
        pixels = width * height
        if pixels > settings.ocr_max_image_pixels_per_frame:
            raise OcrProcessingError(
                f"Image frame {idx + 1} exceeds the configured pixel limit ({pixels} pixels)."
            )
        total_pixels += pixels
        if total_pixels > settings.ocr_max_image_total_pixels:
            raise OcrProcessingError(
                f"Image frames exceed the configured aggregate pixel limit ({total_pixels} pixels)."
            )
    try:
        image.seek(0)
    except Exception:
        pass


def _image_to_pdf(image_path: Path, output_pdf: Path) -> None:
    settings = get_settings()
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image = Image.open(image_path)
        except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise OcrProcessingError("Image exceeds Pillow decompression safety limits.") from exc
        except Exception as exc:
            raise OcrProcessingError("Image could not be opened safely.") from exc
        with image:
            _validate_image_limits(image)
            frames: list[Image.Image] = []
            try:
                frame_count = int(getattr(image, "n_frames", 1) or 1)
                for idx in range(frame_count):
                    image.seek(idx)
                    frame = image.convert("RGB")
                    frames.append(frame.copy())
                    frame.close()
                if not frames:
                    raise OcrProcessingError("Image did not contain any readable frames.")
                first, rest = frames[0], frames[1:]
                first.save(output_pdf, "PDF", save_all=bool(rest), append_images=rest)
            finally:
                for frame in frames:
                    frame.close()
    if not output_pdf.exists() or output_pdf.stat().st_size <= 0:
        raise OcrProcessingError("Image conversion did not create a PDF.")
    if output_pdf.stat().st_size > settings.ocr_max_output_pdf_bytes:
        output_pdf.unlink(missing_ok=True)
        raise OcrProcessingError("Image-converted PDF exceeds the configured output-size limit.")
    _validated_pdf_reader(output_pdf)


class OcrService:
    SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}

    def __init__(self, languages: list[str], timeout_seconds: int = 1800):
        self.languages = tuple(languages or ["guj", "eng"])
        self.timeout_seconds = timeout_seconds
        self.root = Path(tempfile.gettempdir()) / "autodraft_ocr"
        self.root.mkdir(parents=True, exist_ok=True)

    def cleanup_expired(self, max_age_seconds: int) -> None:
        cutoff = time.time() - max(60, max_age_seconds)
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def new_session_dir(self) -> Path:
        path = self.root / str(uuid.uuid4())
        path.mkdir(parents=True, exist_ok=False)
        return path

    async def process_path(self, source: Path, session_dir: Path | None = None) -> OcrResult:
        settings = get_settings()
        suffix = source.suffix.lower()
        if suffix not in self.SUPPORTED_SUFFIXES:
            raise OcrProcessingError(
                "Unsupported OCR input. Use PDF, JPG, JPEG, PNG, TIFF or TIF."
            )
        if not source.is_file():
            raise OcrProcessingError("OCR input file does not exist.")
        if source.stat().st_size > settings.ocr_max_upload_bytes:
            raise OcrProcessingError("OCR input exceeds the configured upload-size limit.")
        session = session_dir or self.new_session_dir()
        input_pdf = session / "input.pdf"
        searchable = session / "searchable.pdf"
        sidecar = session / "ocr-sidecar.txt"
        extracted = session / "extracted.txt"
        subprocess_tmp = session / "work"
        subprocess_tmp.mkdir(parents=True, exist_ok=True)

        if suffix == ".pdf":
            shutil.copy2(source, input_pdf)
            _validated_pdf_reader(input_pdf)
        else:
            await asyncio.to_thread(_image_to_pdf, source, input_pdf)

        initial_text, pages, complete_text = await asyncio.to_thread(_extract_pdf_text, input_pdf)
        if complete_text and initial_text.strip():
            shutil.copy2(input_pdf, searchable)
            extracted.write_text(initial_text, encoding="utf-8")
            return OcrResult(
                searchable_pdf=searchable,
                sidecar_text=None,
                extracted_text=extracted,
                text=initial_text,
                languages=self.languages,
                pages=pages,
                had_complete_text_layer=True,
                ocr_performed=False,
            )

        await ensure_ocr_dependencies(self.languages)
        language_arg = "+".join(self.languages)
        command = (
            "ocrmypdf",
            "-l",
            language_arg,
            "--jobs",
            "1",
            "--rotate-pages",
            "--deskew",
            "--mode",
            "skip",
            "--output-type",
            "pdf",
            "--tesseract-timeout",
            "300",
            "--sidecar",
            str(sidecar),
            str(input_pdf),
            str(searchable),
        )
        code, _stdout, stderr = await _run(
            *command,
            timeout=self.timeout_seconds,
            resource_limited=True,
            temp_dir=subprocess_tmp,
            monitor_dir=session,
        )
        if code != 0:
            raise OcrProcessingError("OCRmyPDF failed: " + stderr[-4000:].strip())
        if not searchable.exists():
            raise OcrProcessingError("OCR completed without creating the searchable PDF.")
        if searchable.stat().st_size > settings.ocr_max_output_pdf_bytes:
            raise OcrProcessingError("Searchable OCR PDF exceeds the configured output-size limit.")
        _validated_pdf_reader(searchable)

        full_text, final_pages, _ = await asyncio.to_thread(_extract_pdf_text, searchable)
        if not full_text.strip() and sidecar.exists():
            if sidecar.stat().st_size > settings.ocr_max_extracted_text_chars * 4:
                raise OcrProcessingError("OCR sidecar text exceeds the configured size limit.")
            full_text = sidecar.read_text(encoding="utf-8", errors="replace").strip()
        if len(full_text) > settings.ocr_max_extracted_text_chars:
            raise OcrProcessingError("OCR text exceeds the configured character limit.")
        if not full_text.strip():
            raise OcrProcessingError("OCR completed but no text was recognised.")
        extracted.write_text(full_text, encoding="utf-8")
        return OcrResult(
            searchable_pdf=searchable,
            sidecar_text=sidecar if sidecar.exists() else None,
            extracted_text=extracted,
            text=full_text,
            languages=self.languages,
            pages=final_pages,
            had_complete_text_layer=complete_text,
            ocr_performed=True,
        )


_SMOKE_CACHE: dict[tuple[str, ...], OcrSmokeStatus] = {}
_SMOKE_LOCK = asyncio.Lock()
_SMOKE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ocr-smoke-guj-eng.png"
_SMOKE_MARKERS = ("ગુજરાતી પરીક્ષણ 12345", "AUTODRAFT ENGLISH TEST 67890")


async def ocr_smoke_status(required: tuple[str, ...] = ("guj", "eng"), *, force: bool = False) -> OcrSmokeStatus:
    settings = get_settings()
    key = tuple(required)
    now = time.time()
    cached = _SMOKE_CACHE.get(key)
    if cached and not force and now - cached.checked_at < max(1, settings.ocr_smoke_cache_seconds):
        return cached
    async with _SMOKE_LOCK:
        cached = _SMOKE_CACHE.get(key)
        now = time.time()
        if cached and not force and now - cached.checked_at < max(1, settings.ocr_smoke_cache_seconds):
            return cached
        deps = await dependency_status(required)
        if not deps.ready:
            result = OcrSmokeStatus(False, now, "OCR dependencies/languages are not ready")
            _SMOKE_CACHE[key] = result
            return result
        if not _SMOKE_FIXTURE.is_file():
            result = OcrSmokeStatus(False, now, "Bundled Gujarati/English OCR smoke fixture is missing")
            _SMOKE_CACHE[key] = result
            return result
        service = OcrService(list(required), min(settings.ocr_timeout_seconds, 300))
        session = service.new_session_dir()
        try:
            source = session / _SMOKE_FIXTURE.name
            shutil.copy2(_SMOKE_FIXTURE, source)
            output = await service.process_path(source, session)
            text = output.text.strip()
            missing = [marker for marker in _SMOKE_MARKERS if marker.casefold() not in text.casefold()]
            if not output.ocr_performed:
                result = OcrSmokeStatus(False, time.time(), "Smoke fixture bypassed OCR instead of exercising it", len(text))
            elif missing:
                result = OcrSmokeStatus(False, time.time(), "OCR smoke output did not contain all Gujarati/English markers", len(text))
            elif not output.searchable_pdf.exists() or output.searchable_pdf.stat().st_size <= 0:
                result = OcrSmokeStatus(False, time.time(), "OCR smoke did not create a searchable PDF", len(text))
            else:
                result = OcrSmokeStatus(True, time.time(), "Gujarati/English OCR pipeline smoke test passed", len(text))
        except Exception as exc:
            result = OcrSmokeStatus(False, time.time(), f"OCR smoke test failed: {type(exc).__name__}")
        finally:
            shutil.rmtree(session, ignore_errors=True)
        _SMOKE_CACHE[key] = result
        return result
