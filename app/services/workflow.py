import json
import hashlib
import logging
from typing import TypedDict, List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from app.core.llm import get_llm, get_embeddings
from app.models.job import Job, JobEmbedding
from app.core.job_settings import (
    get_critical_fields, get_optional_fields,
    is_validation_enabled, is_ai_enabled, is_embedding_enabled,
    VALIDATION_SETTINGS, AI_SETTINGS
)

logger = logging.getLogger(__name__)

STRUCTURED_OUTPUT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pydantic output model
# ---------------------------------------------------------------------------

class JobSummaryOutput(BaseModel):
    summary: str = Field(description="AI-generated summary of the job")
    responsibilities: List[str] = Field(description="Responsibilities extracted from JD")
    skills: List[str] = Field(description="Skills/technologies required")
    project_name: Optional[str] = Field(default=None)
    project_sector: Optional[str] = Field(default=None)
    experience_min: Optional[int] = Field(default=None)
    experience_max: Optional[int] = Field(default=None)


class JobWorkflowState(TypedDict):
    job_id: Optional[UUID]
    company_id: UUID
    created_by: UUID
    input_data: Dict[str, Any]
    db: Session
    errors: List[str]
    validation_result: Optional[Dict[str, Any]]
    ai_summary_data: Optional[Dict[str, Any]]
    vectordb_id: Optional[str]
    needs_clarification: Optional[bool]
    questions: Optional[List[Dict[str, Any]]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_json_response(content: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON."""
    content = content.strip()
    for fence in ("```json", "```"):
        if content.startswith(fence):
            content = content[len(fence):]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find('{'), content.rfind('}')
        if start != -1 and end != -1:
            return json.loads(content[start:end + 1])
        raise


def validate_answer_relevance(field_name: str, answer: str) -> tuple[bool, str]:
    """
    Validate answer relevance in a single, short LLM call.
    Returns (is_valid, error_message).
    """
    try:
        llm = get_llm(temperature=0)
    except Exception as e:
        logger.error(f"LLM load failed for answer validation: {e}")
        return True, ""

    prompt = (
        f'Field: "{field_name}"\nAnswer: "{answer[:300]}"\n'
        'Is this answer relevant to the field? Reply VALID or INVALID:<reason>'
    )
    try:
        response = llm.invoke(prompt)
        text = (response.content if hasattr(response, 'content') else str(response)).strip().upper()
        if text.startswith("VALID"):
            return True, ""
        if text.startswith("INVALID"):
            msg = text.replace("INVALID", "").strip(": ")
            return False, msg or f"Invalid {field_name}. Please provide relevant information."
        return True, ""
    except Exception as e:
        logger.error(f"Answer validation error: {e}")
        return True, ""


# ---------------------------------------------------------------------------
# OPTIMIZED: single LLM call for ALL field checks
# ---------------------------------------------------------------------------

def _batch_check_fields(
    fields: List[str], job_description: str, job_title: str, llm
) -> Dict[str, bool]:
    """
    Check multiple fields in ONE LLM call instead of N calls.
    Returns {field_name: bool}.
    """
    fields_str = ", ".join(fields)
    # Truncate JD to keep tokens low
    jd_snippet = job_description[:600]
    prompt = (
        f'Job Title: {job_title}\n'
        f'JD: "{jd_snippet}"\n\n'
        f'For each field below, reply YES if present in the JD, NO if missing.\n'
        f'Fields: {fields_str}\n\n'
        'Reply ONLY as JSON like: {{"field1": true, "field2": false}}\n'
        'Use lowercase field names exactly as given.'
    )
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        data = parse_json_response(text)
        # Normalise values
        return {f: bool(data.get(f, True)) for f in fields}
    except Exception as e:
        logger.error(f"Batch field check failed: {e}")
        # On failure assume all present to avoid blocking the user
        return {f: True for f in fields}


# ---------------------------------------------------------------------------
# Workflow Nodes
# ---------------------------------------------------------------------------

def validate_job_input_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    OPTIMIZED: validate all critical + optional fields in ONE LLM call
    instead of one call per field.
    """
    logger.info("Node: validate_job_input")

    if not is_validation_enabled():
        return {"validation_result": {"valid": True, "skipped": True}}

    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    job_title = input_data.get('job_title') or 'Position'

    if not job_description:
        return {"errors": ["Job description is required"], "validation_result": {"valid": False}}

    critical_fields = get_critical_fields()
    optional_fields = get_optional_fields()
    all_fields = list(dict.fromkeys(critical_fields + optional_fields))  # deduplicated, ordered

    validation_result = {
        "valid": True,
        "missing_critical_fields": [],
        "missing_optional_fields": []
    }

    # ---- ONE LLM call for all fields ----
    try:
        llm = get_llm(temperature=0)
        presence = _batch_check_fields(all_fields, job_description, job_title, llm)
    except Exception as e:
        logger.error(f"LLM load failed for validation: {e}")
        presence = {f: True for f in all_fields}

    for f in critical_fields:
        if not presence.get(f, True):
            validation_result["missing_critical_fields"].append(f)
            validation_result["valid"] = False

    for f in optional_fields:
        if not presence.get(f, True):
            validation_result["missing_optional_fields"].append(f)

    # Build questions
    ask_questions = False
    questions = []

    question_map = {
        "responsibilities": (
            "The job description doesn't clearly mention responsibilities. "
            "Please describe the key responsibilities and day-to-day tasks for this role."
        ),
        "required_skills": (
            "The job description doesn't clearly mention required skills. "
            "Please list the technical skills and technologies required (e.g., Python, React, AWS)."
        ),
    }

    if validation_result["missing_critical_fields"] and VALIDATION_SETTINGS.get("ask_questions_on_critical_missing", True):
        ask_questions = True
        for f in validation_result["missing_critical_fields"]:
            questions.append({
                "id": f"q_{f}",
                "question": question_map.get(f, f"Please provide details about: {f}"),
                "field_name": f
            })

    if validation_result["missing_optional_fields"] and VALIDATION_SETTINGS.get("ask_questions_on_optional_missing", False):
        ask_questions = True
        for f in validation_result["missing_optional_fields"]:
            questions.append({
                "id": f"q_{f}",
                "question": f"Would you like to provide details about: {f}?",
                "field_name": f
            })

    if ask_questions:
        max_q = VALIDATION_SETTINGS.get("max_clarification_questions", 3)
        questions = questions[:max_q]
        return {
            "job_id": state.get("job_id") or uuid4(),
            "validation_result": validation_result,
            "needs_clarification": True,
            "questions": questions
        }

    return {"validation_result": validation_result}


def generate_ai_summary_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    OPTIMIZED: trimmed prompt, tighter schema, avoids re-serialising full schema.
    """
    logger.info("Node: generate_ai_summary")

    if not is_ai_enabled():
        return {"ai_summary_data": {"summary": "AI summary generation disabled"}}

    if state.get("errors"):
        return {}

    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    job_title = input_data.get('job_title') or 'Position'
    temperature = AI_SETTINGS.get("extraction_temperature", 0.3)

    try:
        llm = get_llm(temperature=temperature)
    except Exception as e:
        logger.error(f"LLM load failed: {e}")
        return {"errors": [f"LLM Provider Error: {e}"]}

    summary_length = AI_SETTINGS.get("summary_length", "2-3 sentences")

    # Structured output path
    if STRUCTURED_OUTPUT_AVAILABLE and AI_SETTINGS.get("use_structured_output", True):
        try:
            structured_llm = llm.with_structured_output(JobSummaryOutput)
            result: JobSummaryOutput = structured_llm.invoke(
                f"Title: {job_title}\nJD: {job_description}\n"
                f"Extract: summary ({summary_length}), responsibilities[], skills[], "
                "project_name, project_sector, experience_min, experience_max."
            )
            if result:
                return {"ai_summary_data": result.model_dump()}
        except Exception as e:
            logger.error(f"Structured output failed: {e}, falling back")

    # Fallback: compact JSON prompt (no full schema dump — saves tokens)
    prompt = (
        f"Title: {job_title}\n"
        f"JD: {job_description[:1500]}\n\n"  # cap JD length
        "Return ONLY valid JSON (no markdown):\n"
        '{"summary":"...","responsibilities":[],"skills":[],'
        '"project_name":null,"project_sector":null,'
        '"experience_min":null,"experience_max":null}'
    )

    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        ai_summary_data = parse_json_response(text)
        logger.info(f"AI summary (fallback): {str(ai_summary_data.get('summary', ''))[:80]}…")
        return {"ai_summary_data": ai_summary_data}
    except Exception as e:
        logger.error(f"AI summary generation error: {e}")
        if AI_SETTINGS.get("use_fallback_on_failure", True):
            return {"ai_summary_data": {
                "summary": "", "responsibilities": [], "skills": [],
                "project_name": None, "project_sector": None,
                "experience_min": None, "experience_max": None
            }}
        return {"errors": [f"AI Summary Generation failed: {e}"]}


def store_simplified_job_node(state: JobWorkflowState) -> Dict[str, Any]:
    """Store or update job in database."""
    logger.info("Node: store_simplified_job")

    if state.get("errors"):
        return {}

    db = state["db"]
    input_data = state["input_data"]
    ai = state.get("ai_summary_data") or {}
    job_id = state.get("job_id") or uuid4()

    try:
        existing = db.query(Job).filter(Job.job_id == job_id).first()

        if existing:
            existing.job_description = input_data.get('job_description')
            if input_data.get('job_title'):
                existing.job_title = input_data['job_title']
            existing.ai_summary = ai.get('summary')
            if ai.get('experience_min') is not None:
                existing.experience_min = ai['experience_min']
            if ai.get('experience_max') is not None:
                existing.experience_max = ai['experience_max']
            existing.updated_at = datetime.utcnow()
            logger.info(f"Updated job: {job_id}")
        else:
            job = Job(
                job_id=job_id,
                company_id=state["company_id"],
                created_by=state["created_by"],
                job_description=input_data.get('job_description'),
                job_title=input_data.get('job_title') or 'Untitled Position',
                job_code='AUTO-' + str(job_id)[:8],
                department='General',
                responsibilities=ai.get('summary', ''),
                required_skills=ai.get('skills', []),
                education_requirements='',
                certifications=[],
                experience_min=ai.get('experience_min') or 0,
                experience_max=ai.get('experience_max'),
                ai_summary=ai.get('summary'),
                ai_embedding_status=False
            )
            db.add(job)
            logger.info(f"Created job: {job_id}")

        db.commit()
        return {"job_id": job_id}

    except Exception as e:
        logger.error(f"Job storage error: {e}")
        db.rollback()
        return {"errors": [f"Job Storage failed: {e}"]}


def create_embedding_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    OPTIMIZED: leaner embedding text — no redundant labels, trimmed to essentials.
    """
    logger.info("Node: create_embedding")

    if not is_embedding_enabled():
        return {"vectordb_id": None}

    if state.get("errors"):
        return {}

    job_id = state.get("job_id")
    if not job_id:
        return {"errors": ["No job_id available for embedding"]}

    db = state["db"]
    ai = state.get("ai_summary_data") or {}

    # Leaner embedding text — remove redundant label prefixes
    parts = [
        state["input_data"].get('job_description', ''),
        ai.get('summary', ''),
        ' '.join(ai.get('responsibilities', [])),
        ' '.join(ai.get('skills', []))
    ]
    embedding_text = ' '.join(p for p in parts if p).strip()

    try:
        vector = get_embeddings().embed_query(embedding_text)
        dimension = len(vector)
        content_hash = hashlib.md5(embedding_text.encode()).hexdigest()

        existing_emb = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).first()

        if existing_emb:
            existing_emb.embedding = vector
            existing_emb.embedding_dimension = dimension
            existing_emb.content_hash = content_hash
            existing_emb.updated_at = datetime.utcnow()
            vectordb_id = str(existing_emb.embedding_id)
        else:
            emb = JobEmbedding(
                embedding_id=uuid4(),
                job_id=job_id,
                embedding=vector,
                embedding_model="default",
                embedding_dimension=dimension,
                content_hash=content_hash
            )
            db.add(emb)
            vectordb_id = str(emb.embedding_id)

        job = db.query(Job).filter(Job.job_id == job_id).first()
        if job:
            job.ai_embedding_status = True
            job.updated_at = datetime.utcnow()

        db.commit()
        logger.info(f"Embedding stored: {vectordb_id}")
        return {"vectordb_id": vectordb_id}

    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return {"errors": [f"Embedding Creation failed: {e}"]}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def should_proceed(state: JobWorkflowState) -> str:
    if state.get("errors"):
        return "stop"
    if state.get("needs_clarification"):
        return "ask_questions"
    return "proceed"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_simplified_workflow() -> StateGraph:
    workflow = StateGraph(JobWorkflowState)

    workflow.add_node("validate_input", validate_job_input_node)
    workflow.add_node("generate_summary", generate_ai_summary_node)
    workflow.add_node("store_job", store_simplified_job_node)
    workflow.add_node("create_embedding", create_embedding_node)
    workflow.add_node("store_draft_job", store_simplified_job_node)

    workflow.add_edge(START, "validate_input")
    workflow.add_conditional_edges(
        "validate_input",
        should_proceed,
        {
            "ask_questions": "store_draft_job",
            "proceed": "generate_summary",
            "stop": END
        }
    )
    workflow.add_edge("store_draft_job", END)
    workflow.add_edge("generate_summary", "store_job")
    workflow.add_edge("store_job", "create_embedding")
    workflow.add_edge("create_embedding", END)

    return workflow


job_workflow = build_simplified_workflow().compile()