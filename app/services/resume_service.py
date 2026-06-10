import hashlib
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.llm import get_embeddings, get_llm
from app.models.job import Job, JobEmbedding
from app.models.resume import (
    Candidate,
    CandidateEmbedding,
    MatchResult,
    ResumeFile,
    ResumeProcessingStatus,
    ResumeValidationStatus,
)
from app.services.workflow import parse_json_response

logger = logging.getLogger(__name__)

ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".txt"}
RESUME_KEYWORDS = {
    "resume",
    "curriculum vitae",
    "experience",
    "education",
    "skills",
    "key skills",
    "professional summary",
    "professional experience",
    "work experience",
    "projects",
    "technologies",
    "employment",
    "certifications",
}


def get_job_or_none(db: Session, job_id: UUID) -> Job | None:
    return db.query(Job).filter(Job.job_id == job_id).first()


def get_resume_files(db: Session, job_id: UUID) -> list[ResumeFile]:
    return (
        db.query(ResumeFile)
        .filter(ResumeFile.job_posting_id == job_id)
        .order_by(ResumeFile.created_at.desc())
        .all()
    )


async def save_resume_files(db: Session, job_id: UUID, files: list[UploadFile]) -> list[ResumeFile]:
    upload_dir = Path(settings.RESUME_UPLOAD_DIR) / str(job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved: list[tuple[ResumeFile, bool]] = []
    for upload in files:
        original_filename = Path(upload.filename or "resume").name
        extension = Path(original_filename).suffix.lower()
        content = await upload.read()
        file_hash = hashlib.md5(content).hexdigest()
        storage_name = f"{uuid4()}_{original_filename}"
        storage_path = upload_dir / storage_name

        with storage_path.open("wb") as buffer:
            buffer.write(content)

        is_duplicate = (
            db.query(ResumeFile)
            .filter(
                ResumeFile.job_posting_id == job_id,
                ResumeFile.file_hash_md5 == file_hash,
            )
            .first() is not None
        )

        resume_file = ResumeFile(
            job_posting_id=job_id,
            original_filename=original_filename,
            storage_path=str(storage_path),
            file_size_bytes=len(content),
            file_hash_md5=file_hash,
        )
        if is_duplicate:
            resume_file.validation_status = ResumeValidationStatus.INVALID
            resume_file.processing_status = ResumeProcessingStatus.FAILED
            resume_file.rejection_reason = "Duplicate resume hash for this job"
        elif extension not in ALLOWED_RESUME_EXTENSIONS:
            resume_file.validation_status = ResumeValidationStatus.INVALID
            resume_file.processing_status = ResumeProcessingStatus.FAILED
            resume_file.rejection_reason = (
                f"Unsupported resume file type: {extension}. "
                "Please upload PDF, DOCX, or TXT."
            )
        db.add(resume_file)
        saved.append(
            (resume_file, is_duplicate or extension not in ALLOWED_RESUME_EXTENSIONS)
        )

    db.commit()

    result: list[ResumeFile] = []
    for resume_file, skip_processing in saved:
        db.refresh(resume_file)
        if not skip_processing:
            from app.tasks.resume_tasks import process_single_resume_task
            try:
                process_single_resume_task.apply_async(
                    args=[str(resume_file.id)],
                    queue="resume_processing",
                )
            except Exception as exc:
                logger.exception("Failed to enqueue resume processing task")
                mark_resume_failed(
                    db,
                    resume_file,
                    f"Failed to enqueue resume processing task: {exc}",
                    remove_local=False,
                )
        result.append(resume_file)

    return result


def delete_resume_file(db: Session, job_id: UUID, resume_file_id: UUID) -> bool:
    resume_file = (
        db.query(ResumeFile)
        .filter(ResumeFile.job_posting_id == job_id, ResumeFile.id == resume_file_id)
        .first()
    )
    if not resume_file:
        return False

    storage_path = Path(resume_file.storage_path)
    if storage_path.exists():
        storage_path.unlink()

    db.delete(resume_file)
    db.commit()
    return True


def process_single_resume(db: Session, resume_file: ResumeFile) -> None:
    resume_file.processing_status = ResumeProcessingStatus.PROCESSING
    db.commit()

    try:
        text = extract_resume_text(resume_file.storage_path)
        valid, reason = validate_resume_text(text)
        if not valid:
            mark_resume_failed(db, resume_file, reason, remove_local=True)
            return

        parsed = extract_candidate_details(text)
        embedding_vector, embedding_model = generate_candidate_embedding(
            text, parsed)
        embedding_dimension = len(embedding_vector)

        duplicate = (
            db.query(ResumeFile)
            .join(Candidate, Candidate.resume_file_id == ResumeFile.id)
            .filter(
                ResumeFile.job_posting_id == resume_file.job_posting_id,
                ResumeFile.file_hash_md5 == resume_file.file_hash_md5,
                ResumeFile.id != resume_file.id,
            )
            .first()
            is not None
        )

        candidate = (
            db.query(Candidate)
            .filter(Candidate.resume_file_id == resume_file.id)
            .first()
        )
        if not candidate:
            candidate = Candidate(resume_file_id=resume_file.id)
            db.add(candidate)

        candidate.full_name = parsed.get("full_name")
        candidate.email = parsed.get("email")
        candidate.phone = parsed.get("phone")
        candidate.total_experience_years = parse_optional_float(
            parsed.get("total_experience_years"))
        candidate.education_degree = parsed.get("education_degree")
        candidate.education_field = parsed.get("education_field")
        candidate.skills = normalize_list(parsed.get("skills"))
        candidate.tech_stack = normalize_list(parsed.get("tech_stack"))
        candidate.sector_experience = normalize_list(
            parsed.get("sector_experience"))
        candidate.raw_text = text
        candidate.is_duplicate = duplicate

        resume_file.validation_status = ResumeValidationStatus.VALID
        resume_file.rejection_reason = None
        resume_file.processing_status = ResumeProcessingStatus.COMPLETED
        db.commit()
        db.refresh(candidate)

        embedding = (
            db.query(CandidateEmbedding)
            .filter(CandidateEmbedding.candidate_id == candidate.id)
            .first()
        )
        content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        if not embedding:
            embedding = CandidateEmbedding(
                candidate_id=candidate.id,
                embedding=embedding_vector,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                content_hash=content_hash,
                generated_at=datetime.utcnow(),
            )
            db.add(embedding)
        else:
            embedding.embedding = embedding_vector
            embedding.embedding_model = embedding_model
            embedding.embedding_dimension = embedding_dimension
            embedding.content_hash = content_hash
            embedding.generated_at = datetime.utcnow()

        db.commit()
        db.refresh(embedding)
        candidate.embedding_id = str(embedding.embedding_id)
        db.commit()
    except Exception as exc:
        logger.exception("Resume processing failed")
        mark_resume_failed(db, resume_file, str(exc), remove_local=False)
        raise


def mark_resume_failed(db: Session, resume_file: ResumeFile, reason: str, remove_local: bool) -> None:
    resume_file.validation_status = ResumeValidationStatus.INVALID
    resume_file.rejection_reason = reason[:500]
    resume_file.processing_status = ResumeProcessingStatus.FAILED
    db.commit()

    if remove_local:
        storage_path = Path(resume_file.storage_path)
        if storage_path.exists():
            storage_path.unlink()


def extract_resume_text(storage_path: str) -> str:
    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError("Uploaded file is missing from local storage")

    extension = path.suffix.lower()
    if extension not in ALLOWED_RESUME_EXTENSIONS:
        raise ValueError(f"Unsupported resume file type: {extension}")

    if extension == ".pdf":
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()

    if extension == ".docx":
        from docx import Document

        document = Document(str(path))
        parts = [
            paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip()
                         for cell in row.cells if cell.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts).strip()

    return path.read_text(encoding="utf-8", errors="ignore").strip()


def validate_resume_text(text: str) -> tuple[bool, str | None]:
    if len(text.strip()) < 200:
        return False, "File does not contain enough readable resume text"

    lowered = text.lower()
    if any(word in lowered for word in ["invoice", "purchase order", "tax invoice", "receipt"]):
        return False, "File appears to be a non-resume document"

    signal_count = sum(1 for keyword in RESUME_KEYWORDS if keyword in lowered)
    if extract_email(text) or extract_phone(text):
        signal_count += 1
    if extract_years_experience(text) is not None:
        signal_count += 1
    if re.search(r"\b(node\.?js|python|react|java|javascript|typescript|sql|aws|docker|fastapi)\b", lowered):
        signal_count += 1

    if signal_count < 2:
        return False, "File content does not look like a valid resume"

    return True, None


def extract_candidate_details(text: str) -> dict[str, Any]:
    fallback = fallback_candidate_extract(text)
    try:
        llm = get_llm(temperature=0.1)
        prompt = f"""Extract candidate details from this resume text.

Return ONLY valid JSON with these keys:
full_name, email, phone, total_experience_years, education_degree, education_field,
skills, tech_stack, sector_experience.

Use null for unknown scalar values and [] for unknown lists.

Resume text:
{text[:12000]}
"""
        response = llm.invoke(prompt)
        content = response.content if hasattr(
            response, "content") else str(response)
        parsed = parse_json_response(content)
        return {**fallback, **{key: value for key, value in parsed.items() if value not in (None, "", [])}}
    except Exception as exc:
        logger.warning(
            "LLM resume extraction failed, using regex fallback: %s", exc)
        return fallback


def fallback_candidate_extract(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = next((line for line in lines[:10] if not extract_email(
        line) and not extract_phone(line)), None)
    skills = extract_section_terms(
        text, ["skills", "technical skills", "technologies"])
    education = extract_section_terms(text, ["education", "academic"])

    return {
        "full_name": name[:200] if name else None,
        "email": extract_email(text),
        "phone": extract_phone(text),
        "total_experience_years": extract_years_experience(text),
        "education_degree": education[0][:150] if education else None,
        "education_field": None,
        "skills": skills,
        "tech_stack": skills,
        "sector_experience": [],
    }


def generate_candidate_embedding(text: str, parsed: dict[str, Any]) -> tuple[list[float], str]:
    embeddings = get_embeddings()
    embedding_text = build_candidate_embedding_text(text, parsed)
    vector = embeddings.embed_query(embedding_text)
    return normalize_embedding_vector(vector), resolve_embedding_model_name()


def build_candidate_embedding_text(text: str, parsed: dict[str, Any]) -> str:
    return f"""Candidate: {parsed.get('full_name') or ''}
Experience: {parsed.get('total_experience_years') or ''}
Education: {parsed.get('education_degree') or ''} {parsed.get('education_field') or ''}
Skills: {', '.join(normalize_list(parsed.get('skills')))}
Tech Stack: {', '.join(normalize_list(parsed.get('tech_stack')))}
Sector Experience: {', '.join(normalize_list(parsed.get('sector_experience')))}
Resume:
{text[:12000]}""".strip()


def resolve_embedding_model_name() -> str:
    provider = (settings.EMBEDDING_PROVIDER or "ollama").lower()
    if provider == "openai":
        return settings.OPENAI_EMBEDDING_MODEL
    if provider == "gemini":
        return settings.HUGGINGFACE_EMBEDDING_MODEL
    return settings.AI_EMBEDDING_MODEL or settings.OLLAMA_EMBEDDING_MODEL or settings.OLLAMA_MODEL or "ollama"


def get_processing_summary(db: Session, job_id: UUID) -> dict[str, Any]:
    db.expire_all()
    rows = (
        db.query(ResumeFile)
        .options(joinedload(ResumeFile.candidate))
        .filter(ResumeFile.job_posting_id == job_id)
        .order_by(ResumeFile.created_at.desc())
        .all()
    )
    completed = sum(1 for row in rows if row.processing_status ==
                    ResumeProcessingStatus.COMPLETED)
    failed = sum(1 for row in rows if row.processing_status ==
                 ResumeProcessingStatus.FAILED)
    pending = sum(1 for row in rows if row.processing_status ==
                  ResumeProcessingStatus.PENDING)
    processing = sum(1 for row in rows if row.processing_status ==
                     ResumeProcessingStatus.PROCESSING)
    return {
        "total": len(rows),
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "processing": processing,
        "logs": [{"resume_file": row, "candidate": row.candidate} for row in rows],
    }


def get_candidates_for_job(db: Session, job_id: UUID) -> list[Candidate]:
    return (
        db.query(Candidate)
        .join(ResumeFile, Candidate.resume_file_id == ResumeFile.id)
        .filter(ResumeFile.job_posting_id == job_id)
        .order_by(Candidate.created_at.desc())
        .all()
    )


def run_matching(db: Session, job_id: UUID) -> list[MatchResult]:
    job = get_job_or_none(db, job_id)
    if not job:
        return []

    candidates = get_candidates_for_job(db, job_id)
    job_secondary_skills = (
        (job.certifications or [])
        + (job.ai_nice_to_have_keywords or [])
        + (job.ai_tools or [])
        + (job.ai_technologies or [])
        + (job.ai_soft_skills or [])
    )
    job_keywords = normalize_keywords(
        (job.required_skills or [])
        + (job.ai_required_skills or [])
        + (job.ai_keywords or [])
        + (job.ai_must_have_keywords or [])
        + job_secondary_skills
        + [job.job_title, job.department, job.education_requirements]
    )

    results: list[MatchResult] = []
    for candidate in candidates:
        candidate_keywords = normalize_keywords(
            (candidate.skills or [])
            + (candidate.tech_stack or [])
            + (candidate.sector_experience or [])
            + [candidate.education_degree,
                candidate.education_field, candidate.raw_text or ""]
        )
        matched = sorted(job_keywords.intersection(candidate_keywords))
        unmatched = sorted(job_keywords.difference(candidate_keywords))
        keyword_score = float((len(matched) / max(len(job_keywords), 1)) * 100)
        semantic_score = float(calculate_semantic_score(db, job, candidate))
        overall = float(round((keyword_score * 0.55) +
                        (semantic_score * 0.45), 2))

        result = (
            db.query(MatchResult)
            .filter(MatchResult.job_posting_id == job_id, MatchResult.candidate_id == candidate.id)
            .first()
        )
        if not result:
            result = MatchResult(
                job_posting_id=job_id, candidate_id=candidate.id, overall_score=overall)
            db.add(result)

        result.overall_score = overall
        result.score_experience = score_experience(job, candidate)
        result.score_sector = keyword_overlap_score(
            job.ai_domain_experience or [], candidate.sector_experience or [])
        result.score_tech_stack = keyword_overlap_score(
            job.required_skills or [], candidate.tech_stack or [])
        result.score_education = 100 if job.education_requirements and candidate.education_degree and candidate.education_degree.lower(
        ) in job.education_requirements.lower() else 0
        result.score_other_skills = keyword_overlap_score(
            job_secondary_skills, (candidate.skills or []) + (candidate.tech_stack or []))
        result.matched_keywords = matched
        result.unmatched_keywords = unmatched
        result.bm25_score = float(round(keyword_score, 4))
        result.semantic_score = float(round(semantic_score, 4))
        result.ai_summary = build_match_summary(
            candidate, matched, unmatched, overall)
        results.append(result)

    db.commit()
    ranked = (
        db.query(MatchResult)
        .options(joinedload(MatchResult.candidate))
        .filter(MatchResult.job_posting_id == job_id)
        .order_by(MatchResult.overall_score.desc())
        .all()
    )
    for index, result in enumerate(ranked, start=1):
        result.rank_position = index
    db.commit()
    return ranked


def get_match_results(db: Session, job_id: UUID, limit: int = 100) -> list[MatchResult]:
    return (
        db.query(MatchResult)
        .options(joinedload(MatchResult.candidate))
        .filter(MatchResult.job_posting_id == job_id)
        .order_by(MatchResult.rank_position.asc().nullslast(), MatchResult.overall_score.desc())
        .limit(limit)
        .all()
    )


def calculate_semantic_score(db: Session, job: Job, candidate: Candidate) -> float:
    job_embedding = (
        db.query(JobEmbedding)
        .filter(JobEmbedding.job_id == job.job_id)
        .first()
    )
    candidate_embedding = (
        db.query(CandidateEmbedding)
        .filter(CandidateEmbedding.candidate_id == candidate.id)
        .first()
    )
    if not job_embedding or not candidate_embedding:
        return 0.0

    job_vector = job_embedding.embedding
    candidate_vector = candidate_embedding.embedding
    if job_vector is None or candidate_vector is None:
        return 0.0
    similarity = float(cosine_similarity(
        list(job_vector), list(candidate_vector)))
    return float(round(max(min(similarity, 1.0), -1.0) * 50 + 50, 4))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = float(sum(float(a) * float(b) for a, b in zip(left, right)))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def score_experience(job: Job, candidate: Candidate) -> float:
    years = float(candidate.total_experience_years or 0)
    experience_min = float(job.experience_min or 0)
    experience_max = float(job.experience_max) if job.experience_max is not None else None

    if years >= experience_min and (experience_max is None or years <= experience_max):
        return 100.0
    if experience_max is not None and years > experience_max:
        return 85.0
    return round((years / max(experience_min, 1)) * 100, 2)


def parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def normalize_embedding_vector(vector: Any) -> list[float]:
    return [float(value) for value in vector]


def keyword_overlap_score(required: list[str], actual: list[str]) -> float:
    required_set = normalize_keywords(required)
    actual_set = normalize_keywords(actual)
    if not required_set:
        return 0.0
    return round((len(required_set.intersection(actual_set)) / len(required_set)) * 100, 2)


def build_match_summary(candidate: Candidate, matched: list[str], unmatched: list[str], overall: float) -> str:
    return (
        f"{candidate.full_name or 'Candidate'} scored {overall:.2f}. "
        f"Matched: {', '.join(matched[:8]) or 'none'}. "
        f"Missing: {', '.join(unmatched[:8]) or 'none'}."
    )


def normalize_keywords(values: list[str | None]) -> set[str]:
    keywords: set[str] = set()
    for value in values:
        if not value:
            continue
        for token in re.split(r"[^a-zA-Z0-9+#.]+", str(value).lower()):
            if len(token) > 1:
                keywords.add(token)
    return keywords


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]
    return []


def extract_email(text: str) -> str | None:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else None


def extract_phone(text: str) -> str | None:
    match = re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)
    return match.group(1).strip() if match else None


def extract_years_experience(text: str) -> float | None:
    matches = re.findall(
        r"(\d+(?:\.\d+)?)\+?\s*(?:years|yrs)\s+(?:of\s+)?experience", text, re.IGNORECASE)
    if not matches:
        return None
    return max(float(match) for match in matches)


def extract_section_terms(text: str, headings: list[str]) -> list[str]:
    lowered = text.lower()
    for heading in headings:
        start = lowered.find(heading)
        if start == -1:
            continue
        snippet = text[start: start + 800]
        terms = re.split(r"[,|;\n]", snippet)
        return [term.strip(" -:\t") for term in terms[1:25] if 1 < len(term.strip()) < 80]
    return []
