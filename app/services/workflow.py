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
    summary: str = Field(description="AI-generated summary of the job. MUST explicitly mention responsibilities, required skills, and min/max years of experience in the text itself.")
    responsibilities: List[str] = Field(description="Responsibilities extracted from JD")
    skills: List[str] = Field(description="Skills/technologies required")
    must_have_skills: List[str] = Field(description="Must-have skills that are absolutely required for this role (5-8 most critical skills)")
    good_to_have_skills: List[str] = Field(description="Good-to-have skills that are nice to have but not mandatory")
    skill_tiers: Dict[str, str] = Field(description="Skill tier classification: {skill_name: mandatory|preferred|bonus}")
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
    print("=== VALIDATION START ===")
    logger.info("Node: validate_job_input")

    if not is_validation_enabled():
        print("Validation is disabled in settings")
        logger.info("Validation is disabled in settings")
        return {"validation_result": {"valid": True, "skipped": True}}

    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    job_title = input_data.get('job_title') or 'Position'

    print(f"Validation - Job title: {job_title}")
    print(f"Validation - JD length: {len(job_description)} chars")
    print(f"Validation - JD preview: {job_description[:200]}...")
    logger.info(f"Validation - Job title: {job_title}")
    logger.info(f"Validation - JD length: {len(job_description)} chars")
    logger.info(f"Validation - JD preview: {job_description[:200]}...")

    if not job_description:
        print("Job description is empty - returning error")
        logger.error("Job description is empty - returning error")
        return {"errors": ["Job description is required"], "validation_result": {"valid": False}}

    critical_fields = get_critical_fields()
    optional_fields = get_optional_fields()
    all_fields = list(dict.fromkeys(critical_fields + optional_fields))  # deduplicated, ordered

    print(f"Critical fields: {critical_fields}")
    print(f"Optional fields: {optional_fields}")
    logger.info(f"Critical fields: {critical_fields}")
    logger.info(f"Optional fields: {optional_fields}")

    validation_result = {
        "valid": True,
        "missing_critical_fields": [],
        "missing_optional_fields": []
    }

    # ---- ONE LLM call for all fields ----
    try:
        llm = get_llm(temperature=0)
        presence = _batch_check_fields(all_fields, job_description, job_title, llm)
        print(f"Field presence check result: {presence}")
        logger.info(f"Field presence check result: {presence}")
    except Exception as e:
        print(f"LLM load failed for validation: {e}")
        logger.error(f"LLM load failed for validation: {e}")
        presence = {f: True for f in all_fields}

    for f in critical_fields:
        if not presence.get(f, True):
            validation_result["missing_critical_fields"].append(f)
            validation_result["valid"] = False

    for f in optional_fields:
        if not presence.get(f, True):
            validation_result["missing_optional_fields"].append(f)

    print(f"Missing critical fields: {validation_result['missing_critical_fields']}")
    print(f"Missing optional fields: {validation_result['missing_optional_fields']}")
    print(f"Validation result valid: {validation_result['valid']}")
    logger.info(f"Missing critical fields: {validation_result['missing_critical_fields']}")
    logger.info(f"Missing optional fields: {validation_result['missing_optional_fields']}")
    logger.info(f"Validation result valid: {validation_result['valid']}")

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
    print("=== AI EXTRACTION START ===")
    logger.info("Node: generate_ai_summary")

    print(f"STRUCTURED_OUTPUT_AVAILABLE: {STRUCTURED_OUTPUT_AVAILABLE}")
    print(f"AI_SETTINGS: {AI_SETTINGS}")
    print(f"is_ai_enabled(): {is_ai_enabled()}")
    logger.info(f"STRUCTURED_OUTPUT_AVAILABLE: {STRUCTURED_OUTPUT_AVAILABLE}")
    logger.info(f"AI_SETTINGS: {AI_SETTINGS}")
    logger.info(f"is_ai_enabled(): {is_ai_enabled()}")

    if not is_ai_enabled():
        print("AI summary generation is disabled in settings")
        logger.warning("AI summary generation is disabled in settings")
        return {"ai_summary_data": {"summary": "AI summary generation disabled"}}

    if state.get("errors"):
        print(f"Skipping AI summary due to errors: {state.get('errors')}")
        logger.error(f"Skipping AI summary due to errors: {state.get('errors')}")
        return {}

    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    job_title = input_data.get('job_title') or 'Position'
    temperature = AI_SETTINGS.get("extraction_temperature", 0.3)

    print(f"AI extraction - Job title: {job_title}")
    print(f"AI extraction - JD length: {len(job_description)} chars")
    print(f"AI extraction - JD preview: {job_description[:200]}...")
    print(f"AI extraction - Full JD: {job_description}")
    logger.info(f"AI extraction - Job title: {job_title}")
    logger.info(f"AI extraction - JD length: {len(job_description)} chars")
    logger.info(f"AI extraction - JD preview: {job_description[:200]}...")

    try:
        llm = get_llm(temperature=temperature)
        print(f"LLM loaded successfully: {type(llm)}")
    except Exception as e:
        print(f"LLM load failed: {e}")
        logger.error(f"LLM load failed: {e}")
        return {"errors": [f"LLM Provider Error: {e}"]}

    summary_length = AI_SETTINGS.get("summary_length", "2-3 sentences")

    # Structured output path
    if STRUCTURED_OUTPUT_AVAILABLE and AI_SETTINGS.get("use_structured_output", True):
        try:
            print("Using structured output extraction...")
            structured_llm = llm.with_structured_output(JobSummaryOutput)
            result: JobSummaryOutput = structured_llm.invoke(
                f"Job Title: {job_title}\n\n"
                f"Job Description:\n{job_description}\n\n"
                f"TASK: Extract structured information from this job description.\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Extract ALL skills/technologies mentioned, including:\n"
                f"   - Programming languages (Java, Python, Scala, etc.)\n"
                f"   - Cloud platforms (AWS, Azure, GCP, etc.)\n"
                f"   - Frameworks (TensorFlow, PyTorch, Spark, etc.)\n"
                f"   - Tools (Docker, Kafka, Maven, etc.)\n"
                f"   - Concepts (CI/CD, MLOps, RAG, etc.)\n"
                f"   - Include skills from ALL sections (Must-Have, Good to Have, etc.)\n"
                f"2. SEPARATE skills into MUST-HAVE vs GOOD-TO-HAVE:\n"
                f"   - Must-have: 5-8 most critical skills absolutely required for the role\n"
                f"   - Good-to-have: Nice-to-have skills that are not mandatory\n"
                f"   - Look for explicit sections like 'Must-Have Skills' vs 'Good to Have'\n"
                f"   - If not explicitly separated, prioritize core technologies as must-have\n"
                f"3. CLASSIFY each skill into a tier: mandatory, preferred, or bonus\n"
                f"   - mandatory: Absolutely required, dealbreaker if missing\n"
                f"   - preferred: Strongly desired but not a dealbreaker\n"
                f"   - bonus: Nice-to-have, peripheral skills\n"
                f"   - Return as JSON: {{\"python\": \"mandatory\", \"kafka\": \"preferred\", \"scala\": \"bonus\"}}\n"
                f"4. Extract responsibilities/duties mentioned\n"
                f"5. Extract minimum and maximum years of experience if mentioned\n"
                f"6. Handle various formats: bullet points, emojis (🔹, ✔, ➕), numbered lists\n"
                f"7. Generate a brief 2-3 sentence summary of the role"
            )
            if result:
                print(f"AI extraction (structured) - Skills extracted: {result.skills}")
                print(f"AI extraction (structured) - Responsibilities: {result.responsibilities}")
                print(f"AI extraction (structured) - Exp min/max: {result.experience_min}/{result.experience_max}")
                logger.info(f"AI extraction (structured) - Skills extracted: {result.skills}")
                logger.info(f"AI extraction (structured) - Responsibilities: {result.responsibilities}")
                logger.info(f"AI extraction (structured) - Exp min/max: {result.experience_min}/{result.experience_max}")
                return {"ai_summary_data": result.model_dump()}
        except Exception as e:
            print(f"Structured output failed: {e}, falling back")
            logger.error(f"Structured output failed: {e}, falling back")

    # Fallback: compact JSON prompt (no full schema dump — saves tokens)
    print("Using fallback JSON extraction...")
    prompt = (
        f"Title: {job_title}\n"
        f"Job Description:\n{job_description}\n\n"
        "TASK: Extract structured information from this job description.\n\n"
        "INSTRUCTIONS:\n"
        "1. Extract ALL skills/technologies mentioned, including:\n"
        "   - Programming languages (Java, Python, Scala, etc.)\n"
        "   - Cloud platforms (AWS, Azure, GCP, etc.)\n"
        "   - Frameworks (TensorFlow, PyTorch, Spark, etc.)\n"
        "   - Tools (Docker, Kafka, Maven, etc.)\n"
        "   - Concepts (CI/CD, MLOps, RAG, etc.)\n"
        "   - Include skills from ALL sections (Must-Have, Good to Have, etc.)\n"
        "2. SEPARATE skills into MUST-HAVE vs GOOD-TO-HAVE:\n"
        "   - Must-have: 5-8 most critical skills absolutely required for the role\n"
        "   - Good-to-have: Nice-to-have skills that are not mandatory\n"
        "   - Look for explicit sections like 'Must-Have Skills' vs 'Good to Have'\n"
        "   - If not explicitly separated, prioritize core technologies as must-have\n"
        "3. CLASSIFY each skill into a tier: mandatory, preferred, or bonus\n"
        "   - mandatory: Absolutely required, dealbreaker if missing\n"
        "   - preferred: Strongly desired but not a dealbreaker\n"
        "   - bonus: Nice-to-have, peripheral skills\n"
        "   - Return as JSON: {\"python\": \"mandatory\", \"kafka\": \"preferred\", \"scala\": \"bonus\"}\n"
        "4. Extract responsibilities/duties mentioned\n"
        "5. Extract minimum and maximum years of experience if mentioned\n"
        "6. Handle various formats: bullet points, emojis (🔹, ✔, ➕), numbered lists\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{"summary":"Brief 2-3 sentence summary of the role",'
        '"responsibilities":["responsibility1","responsibility2"],'
        '"skills":["skill1","skill2","skill3"],'
        '"must_have_skills":["critical1","critical2"],'
        '"good_to_have_skills":["nice1","nice2"],'
        '"skill_tiers":{"python":"mandatory","kafka":"preferred","scala":"bonus"},'
        '"project_name":null,"project_sector":null,'
        '"experience_min":number or null,"experience_max":number or null}'
    )

    try:
        print(f"Invoking LLM with prompt length: {len(prompt)}")
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        print(f"LLM response length: {len(text)}")
        print(f"LLM response preview: {text[:500]}...")
        ai_summary_data = parse_json_response(text)
        print(f"AI extraction (fallback) - Skills extracted: {ai_summary_data.get('skills', [])}")
        print(f"AI extraction (fallback) - Responsibilities: {ai_summary_data.get('responsibilities', [])}")
        print(f"AI extraction (fallback) - Summary: {str(ai_summary_data.get('summary', ''))[:80]}…")
        logger.info(f"AI extraction (fallback) - Skills extracted: {ai_summary_data.get('skills', [])}")
        logger.info(f"AI extraction (fallback) - Responsibilities: {ai_summary_data.get('responsibilities', [])}")
        logger.info(f"AI extraction (fallback) - Summary: {str(ai_summary_data.get('summary', ''))[:80]}…")
        return {"ai_summary_data": ai_summary_data}
    except Exception as e:
        print(f"AI summary generation error: {e}")
        logger.error(f"AI summary generation error: {e}")
        if AI_SETTINGS.get("use_fallback_on_failure", True):
            print("Using fallback empty data due to AI failure")
            logger.warning("Using fallback empty data due to AI failure")
            return {"ai_summary_data": {
                "summary": "", "responsibilities": [], "skills": [],
                "project_name": None, "project_sector": None,
                "experience_min": None, "experience_max": None
            }}
        return {"errors": [f"AI Summary Generation failed: {e}"]}


def store_simplified_job_node(state: JobWorkflowState) -> Dict[str, Any]:
    """Store or update job in database."""
    print("=== JOB STORAGE START ===")
    logger.info("Node: store_simplified_job")

    if state.get("errors"):
        return {}

    db = state["db"]
    input_data = state["input_data"]
    ai = state.get("ai_summary_data") or {}
    job_id = state.get("job_id") or uuid4()

    print(f"Job storage - AI skills from extraction: {ai.get('skills', [])}")
    print(f"Job storage - User provided skills: {input_data.get('required_skills', [])}")
    print(f"Job storage - AI summary: {str(ai.get('summary', ''))[:100]}...")
    logger.info(f"Job storage - AI skills from extraction: {ai.get('skills', [])}")
    logger.info(f"Job storage - User provided skills: {input_data.get('required_skills', [])}")
    logger.info(f"Job storage - AI summary: {str(ai.get('summary', ''))[:100]}...")

    try:
        existing = db.query(Job).filter(Job.job_id == job_id).first()

        if existing:
            existing.job_description = input_data.get('job_description')
            if input_data.get('job_title'):
                existing.job_title = input_data['job_title']
            existing.ai_summary = ai.get('summary')
            existing.ai_required_skills = ai.get('skills', [])
            existing.ai_must_have_keywords = ai.get('must_have_skills', ai.get('skills', []))
            existing.ai_nice_to_have_keywords = ai.get('good_to_have_skills', [])
            existing.ai_keywords = ai.get('skills', [])
            existing.ai_technologies = ai.get('skills', [])
            existing.skill_tiers = ai.get('skill_tiers', {})
            if ai.get('experience_min') is not None:
                existing.experience_min = ai['experience_min']
            if ai.get('experience_max') is not None:
                existing.experience_max = ai['experience_max']
            existing.updated_at = datetime.utcnow()
            print(f"Updated job: {job_id}")
            print(f"Updated job - ai_required_skills: {existing.ai_required_skills}")
            print(f"Updated job - ai_must_have_keywords: {existing.ai_must_have_keywords}")
            print(f"Updated job - skill_tiers: {existing.skill_tiers}")
            logger.info(f"Updated job: {job_id}")
            logger.info(f"Updated job - ai_required_skills: {existing.ai_required_skills}")
            logger.info(f"Updated job - ai_must_have_keywords: {existing.ai_must_have_keywords}")
            logger.info(f"Updated job - skill_tiers: {existing.skill_tiers}")
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
                required_skills=input_data.get('required_skills', []),
                education_requirements='',
                certifications=[],
                experience_min=ai.get('experience_min') or 0,
                experience_max=ai.get('experience_max'),
                ai_summary=ai.get('summary'),
                ai_required_skills=ai.get('skills', []),
                ai_must_have_keywords=ai.get('must_have_skills', ai.get('skills', [])),
                ai_nice_to_have_keywords=ai.get('good_to_have_skills', []),
                ai_keywords=ai.get('skills', []),
                ai_tools=[],
                ai_technologies=ai.get('skills', []),
                ai_soft_skills=[],
                ai_domain_experience=[],
                ai_embedding_status=False,
                skill_tiers=ai.get('skill_tiers', {})
            )
            db.add(job)
            print(f"Created job: {job_id}")
            print(f"Created job - ai_required_skills: {job.ai_required_skills}")
            print(f"Created job - ai_must_have_keywords: {job.ai_must_have_keywords}")
            print(f"Created job - required_skills: {job.required_skills}")
            print(f"Created job - skill_tiers: {job.skill_tiers}")
            logger.info(f"Created job: {job_id}")
            logger.info(f"Created job - ai_required_skills: {job.ai_required_skills}")
            logger.info(f"Created job - ai_must_have_keywords: {job.ai_must_have_keywords}")
            logger.info(f"Created job - required_skills: {job.required_skills}")
            logger.info(f"Created job - skill_tiers: {job.skill_tiers}")

        db.commit()
        return {"job_id": job_id}

    except Exception as e:
        print(f"Job storage error: {e}")
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
    workflow.add_edge("store_job", END)

    return workflow


job_workflow = build_simplified_workflow().compile()