import json
import hashlib
import logging
from typing import TypedDict, List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END

from app.core.llm import get_llm, get_embeddings
from app.models.job import Job, JobEmbedding, EmploymentType, WorkMode, JobStatus

logger = logging.getLogger(__name__)

class JobWorkflowState(TypedDict):
    job_id: Optional[UUID]
    company_id: UUID
    created_by: UUID
    input_data: Dict[str, Any]
    db: Session
    errors: List[str]

    ai_summary: Optional[str]
    ai_extracted_metadata: Optional[Dict[str, Any]]
    ai_keywords: Optional[Dict[str, Any]]

    embedding_text: Optional[str]
    embedding_vector: Optional[List[float]]
    embedding_dimension: Optional[int]
    embedding_model_name: Optional[str]
    embedding_text: Optional[str]
    embedding_vector: Optional[List[float]]
    embedding_dimension: Optional[int]
    embedding_model_name: Optional[str]

    needs_clarification: Optional[bool]
    questions: Optional[List[Dict[str, Any]]]


def is_insufficient_data(value: Any) -> bool:
    """
    Check if a value represents insufficient/placeholder data.
    Returns True if the value is None, empty string, "emergency", "TBD", "to be determined", etc.
    """
    if value is None:
        return True
    if isinstance(value, str):
        value_lower = value.strip().lower()
        placeholder_indicators = [
            "emergency", "tbd", "to be determined", "pending", "not specified",
            "not provided", "n/a", "na", "unknown", "tba", "to be announced",
            "placeholder", "temp", "temporary", "-"
        ]
        return value_lower == "" or any(indicator in value_lower for indicator in placeholder_indicators)
    if isinstance(value, list):
        return len(value) == 0
    return False


def generate_clarifying_questions_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    Generate clarifying questions using LLM when data is insufficient.
    Uses job_settings configuration to determine which fields to ask about.
    """
    logger.info("LangGraph Node: generate_clarifying_questions")
    
    from app.core.job_settings import get_fields_to_ask
    
    input_data = state["input_data"]
    
    fields_to_ask = get_fields_to_ask()
    
    insufficient_fields = []
    for field_config in fields_to_ask:
        field_name = field_config["field_name"]
        description = field_config["description"]
        value = input_data.get(field_name)
        if is_insufficient_data(value):
            insufficient_fields.append((field_name, description, value, field_config))
    
    if not insufficient_fields:
        return {"needs_clarification": False, "questions": []}
    
    try:
        llm = get_llm(temperature=0.3)
    except Exception as e:
        logger.error(f"Failed to load LLM in generate_clarifying_questions: {e}")
        return {"errors": [f"LLM Provider Error: {e}"]}
    
    field_name, description, value, field_config = insufficient_fields[0]
    prompt_template = field_config.get("prompt_template", f"Please provide the {description.lower()}")
    
    prompt = f"""You are an expert recruitment assistant. Analyze the following job data and generate ONE specific clarifying question.

Job Title: {input_data.get('job_title')}
Job Description: {input_data.get('job_description')}

The field that needs clarification: {description} (current value: '{value}')

Generate ONE specific, clarifying question to ask the user about this missing information. The question should:
1. Be specific and actionable
2. Relate to the missing field: {field_name}
3. Help complete the job posting

Use this prompt template as a guide: {prompt_template}

Return a JSON object with this structure:
{{
  "id": "q1",
  "question": "What is the department for this position?",
  "field_name": "{field_name}"
}}

Use the field name: {field_name}

Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations.
"""
    
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        question_data = parse_json_response(text)
        return {
            "needs_clarification": True,
            "questions": [question_data]
        }
    except Exception as e:
        logger.error(f"Error invoking LLM in generate_clarifying_questions: {e}")
        return {
            "needs_clarification": True,
            "questions": [{
                "id": "q1",
                "question": prompt_template,
                "field_name": field_name
            }]
        }


def parse_json_response(content: str) -> Dict[str, Any]:
    """
    Safely clean and parse JSON responses from the LLM,
    stripping markdown block tags if present.
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON: {content}. Error: {e}")
        # Try finding the first '{' and last '}'
        start_idx = content.find('{')
        end_idx = content.rfind('}')
        if start_idx != -1 and end_idx != -1:
            try:
                return json.loads(content[start_idx:end_idx+1])
            except Exception:
                pass
        raise e

def validate_input_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: validate_input")
    input_data = state.get("input_data", {})
    errors = []

    if not input_data.get("job_title"):
        errors.append("job_title is required")
    if not input_data.get("job_description"):
        errors.append("job_description is required")

    if errors:
        return {"errors": errors}
    
    if not state.get("job_id"):
        return {"job_id": str(uuid4())}
    
    return {}


def store_job_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: store_job")
    if state.get("errors"):
        return {}

    db = state["db"]
    input_data = state["input_data"]
    job_id = state.get("job_id")

    employment_type_str = input_data.get("employment_type", "")
    try:
        employment_type = EmploymentType(employment_type_str) if employment_type_str else EmploymentType.FULL_TIME
    except (ValueError, KeyError):
        employment_type = EmploymentType.FULL_TIME

    work_mode_str = input_data.get("work_mode", "")
    try:
        work_mode = WorkMode(work_mode_str) if work_mode_str else WorkMode.ONSITE
    except (ValueError, KeyError):
        work_mode = WorkMode.ONSITE

    status = JobStatus.DRAFT
    if "status" in input_data:
        try:
            status = JobStatus(input_data["status"])
        except (ValueError, KeyError):
            pass

    job = None
    if job_id:
        job = db.query(Job).filter(Job.job_id == job_id).first()

    if not job:
        from app.core.job_settings import get_all_fields, get_default_value
        
        job_data = {
            "job_id": job_id or uuid4(),
            "company_id": state["company_id"],
            "created_by": state["created_by"],
            "job_title": input_data["job_title"],
            "job_code": input_data.get("job_code", ""),
            "currency": input_data.get("currency", "USD"),
            "vacancies": input_data.get("vacancies", 1),
            "notice_period_max": input_data.get("notice_period_max", 30),
            "job_description": input_data["job_description"],
            "preferred_skills": input_data.get("preferred_skills", []),
            "status": status,
            "industry": input_data.get("industry"),
            "team_name": input_data.get("team_name"),
            "project_name": input_data.get("project_name"),
            "benefits": input_data.get("benefits"),
            "working_hours": input_data.get("working_hours"),
            "shift_details": input_data.get("shift_details"),
            "travel_requirements": input_data.get("travel_requirements"),
            "relocation_support": input_data.get("relocation_support", False),
            "visa_sponsorship": input_data.get("visa_sponsorship", False),
            "internal_notes": input_data.get("internal_notes"),
        }
        
        for field_config in get_all_fields():
            field_name = field_config["field_name"]
            job_data[field_name] = input_data.get(field_name, field_config["default_value"])
        
        job_data["employment_type"] = employment_type
        job_data["work_mode"] = work_mode
        
        job = Job(**job_data)
        db.add(job)
    else:
        job.job_title = input_data["job_title"]
        job.job_code = input_data["job_code"]
        job.department = input_data["department"]
        job.employment_type = employment_type
        job.work_mode = work_mode
        job.experience_min = input_data["experience_min"]
        job.experience_max = input_data["experience_max"]
        job.salary_min = input_data["salary_min"]
        job.salary_max = input_data["salary_max"]
        job.currency = input_data.get("currency", job.currency)
        job.vacancies = input_data.get("vacancies", job.vacancies)
        job.location_country = input_data["location_country"]
        job.location_state = input_data["location_state"]
        job.location_city = input_data["location_city"]
        job.notice_period_max = input_data.get("notice_period_max", job.notice_period_max)
        job.job_description = input_data["job_description"]
        job.responsibilities = input_data["responsibilities"]
        job.required_skills = input_data.get("required_skills", job.required_skills)
        job.preferred_skills = input_data.get("preferred_skills", job.preferred_skills)
        job.education_requirements = input_data["education_requirements"]
        job.certifications = input_data.get("certifications", job.certifications)
        job.status = status
        
        for field in [
            "industry", "team_name", "project_name", "benefits", "working_hours",
            "shift_details", "travel_requirements", "relocation_support", "visa_sponsorship", "internal_notes"
        ]:
            if field in input_data:
                setattr(job, field, input_data[field])

    db.commit()
    db.refresh(job)

    return {"job_id": job.job_id}


def generate_ai_summary_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: generate_ai_summary")
    if state.get("errors"):
        return {}

    input_data = state["input_data"]
    try:
        llm = get_llm(temperature=0.3)
    except Exception as e:
        logger.error(f"Failed to load LLM in generate_ai_summary: {e}")
        return {"errors": [f"LLM Provider Error: {e}"]}

    prompt = f"""You are an AI assistant for recruiters. Write a professional, concise summary (2-3 sentences) of the following job description:

Job Title: {input_data.get('job_title')}
Department: {input_data.get('department')}
Description: {input_data.get('job_description')}
Responsibilities: {input_data.get('responsibilities')}

Example Summary:
"Senior Backend Engineer with 3-5 years experience in Python, FastAPI and PostgreSQL. Strong understanding of REST APIs, Docker and cloud deployment preferred."

Write ONLY the summary. Do not include any greeting, introduction, conversational filler, or markdown block code.
"""
    try:
        response = llm.invoke(prompt)
        ai_summary = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        return {"ai_summary": ai_summary}
    except Exception as e:
        logger.error(f"Error invoking LLM in generate_ai_summary: {e}")
        return {"errors": [f"LLM Summarization invocation failed: {e}"]}


def extract_skills_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: extract_skills")
    if state.get("errors"):
        return {}

    input_data = state["input_data"]
    try:
        llm = get_llm(temperature=0.1)
    except Exception as e:
        return {"errors": [f"LLM Provider Error: {e}"]}

    prompt = f"""You are an expert recruitment AI. Extract details from the following job description:

Job Title: {input_data.get('job_title')}
Description: {input_data.get('job_description')}
Responsibilities: {input_data.get('responsibilities')}
Education Requirements: {input_data.get('education_requirements')}
Certifications: {', '.join(input_data.get('certifications', []))}
Required Skills: {', '.join(input_data.get('required_skills', []))}
Preferred Skills: {', '.join(input_data.get('preferred_skills', []))}

Return a JSON object with the following keys. Values MUST be lists of strings unless specified otherwise:
- primary_skills: key technical skills/languages needed.
- secondary_skills: other helpful skills.
- mandatory_skills: absolute must-have skills.
- nice_to_have_skills: preferred/optional skills.
- tools: software tools mentioned.
- frameworks: libraries/frameworks mentioned.
- databases: database systems mentioned.
- cloud_technologies: cloud platforms/services.
- soft_skills: interpersonal/soft skills.
- domain_experience: industries/domains mentioned.
- seniority_level: string (e.g. Junior, Mid, Senior, Lead, Executive).
- job_category: string (e.g. Engineering, Sales, Product, Marketing, Finance).
- education: string (e.g. Bachelor's in CS, High School).
- certifications: list of certifications.
- years_experience: range or string (e.g. "3-5 years").
- notice_period: string (e.g. "30 days").
- location_preferences: location requirements/preferences.

Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations.
"""
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        extracted = parse_json_response(text)
        return {"ai_extracted_metadata": extracted}
    except Exception as e:
        logger.error(f"Error invoking LLM in extract_skills: {e}")
        return {"ai_extracted_metadata": {}}


def generate_searchable_keywords_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: generate_searchable_keywords")
    if state.get("errors"):
        return {}

    input_data = state["input_data"]
    ai_summary = state.get("ai_summary", "")

    try:
        llm = get_llm(temperature=0.1)
    except Exception as e:
        return {"errors": [f"LLM Provider Error: {e}"]}

    prompt = f"""Given the following job details and AI summary:
Job Title: {input_data.get('job_title')}
Description: {input_data.get('job_description')}
AI Summary: {ai_summary}

Extract search keywords. Return a JSON object with:
- keywords: general search keywords (list of strings).
- must_have_keywords: keywords representing absolute must-haves (list of strings).
- nice_to_have_keywords: keywords representing preferred qualities (list of strings).

Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations.
"""
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        keywords = parse_json_response(text)
        return {"ai_keywords": keywords}
    except Exception as e:
        logger.error(f"Error invoking LLM in generate_searchable_keywords: {e}")
        return {"ai_keywords": {}}


def create_embedding_text_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: create_embedding_text")
    if state.get("errors"):
        return {}

    input_data = state["input_data"]
    ai_summary = state.get("ai_summary", "")
    extracted = state.get("ai_extracted_metadata") or {}
    keywords = state.get("ai_keywords") or {}

    req_skills = ", ".join(input_data.get("required_skills") or [])
    pref_skills = ", ".join(input_data.get("preferred_skills") or [])
    certifications = ", ".join(input_data.get("certifications") or [])

    ai_primary = ", ".join(extracted.get("primary_skills") or [])
    ai_secondary = ", ".join(extracted.get("secondary_skills") or [])
    ai_tools = ", ".join(extracted.get("tools") or [])
    ai_frameworks = ", ".join(extracted.get("frameworks") or [])
    ai_db = ", ".join(extracted.get("databases") or [])
    ai_cloud = ", ".join(extracted.get("cloud_technologies") or [])
    ai_soft = ", ".join(extracted.get("soft_skills") or [])
    ai_domain = ", ".join(extracted.get("domain_experience") or [])

    kw_general = ", ".join(keywords.get("keywords") or [])
    kw_must = ", ".join(keywords.get("must_have_keywords") or [])
    kw_nice = ", ".join(keywords.get("nice_to_have_keywords") or [])

    embedding_text = f"""Job Title: {input_data.get('job_title')}
Department: {input_data.get('department')}
Experience range: {input_data.get('experience_min')} to {input_data.get('experience_max')} years. Seniority Level: {extracted.get('seniority_level', '')}
Location: {input_data.get('location_city')}, {input_data.get('location_state')}, {input_data.get('location_country')}
Required Skills: {req_skills}
Preferred Skills: {pref_skills}
Responsibilities: {input_data.get('responsibilities')}
Job Description: {input_data.get('job_description')}
Education Requirements: {input_data.get('education_requirements')}. AI Education: {extracted.get('education', '')}
Certifications: {certifications}

AI Extracted Skills: Primary: {ai_primary} | Secondary: {ai_secondary}
AI Extracted Tools & Tech: Tools: {ai_tools} | Frameworks: {ai_frameworks} | Databases: {ai_db} | Cloud: {ai_cloud}
AI Soft Skills: {ai_soft}
AI Domain Experience: {ai_domain}
AI Job Category: {extracted.get('job_category', '')}

AI Keywords: General: {kw_general} | Must Have: {kw_must} | Nice to Have: {kw_nice}
AI Summary: {ai_summary}"""

    return {"embedding_text": embedding_text.strip()}


def generate_embedding_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: generate_embedding")
    if state.get("errors"):
        return {}

    embedding_text = state.get("embedding_text")
    if not embedding_text:
        return {"errors": ["No embedding text compiled"]}

    try:
        embeddings_client = get_embeddings()
    except Exception as e:
        logger.error(f"Failed to load Embeddings client: {e}")
        return {"errors": [f"Embeddings Provider Error: {e}"]}

    from app.core.config import settings
    embedding_model = settings.EMBEDDING_PROVIDER or "ollama"
    if embedding_model == "ollama":
        model_name = getattr(settings, "AI_EMBEDDING_MODEL", None) or (
            getattr(settings, "OLLAMA_EMBEDDING_MODEL", None) or "nomic-embed-text-v2-moe"
        )
    elif embedding_model == "openai":
        model_name = getattr(settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    elif embedding_model == "gemini":
        model_name = getattr(settings, "AI_EMBEDDING_MODEL", None) or "models/text-embedding-004"
    elif embedding_model in ("azure_openai", "azure"):
        model_name = getattr(settings, "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "azure-embedding")
    else:
        model_name = "unknown"


    try:
        vector = embeddings_client.embed_query(embedding_text)
        dimension = len(vector)
        return {
            "embedding_vector": vector,
            "embedding_dimension": dimension,
            "embedding_model_name": model_name
        }
    except Exception as e:
        logger.error(f"Error generating embedding vector: {e}")
        return {"errors": [f"Embedding Generation failed: {e}"]}


def store_vector_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: store_vector")
    if state.get("errors"):
        return {}

    db = state["db"]
    job_id = state["job_id"]
    vector = state["embedding_vector"]
    dimension = state["embedding_dimension"]
    model_name = state["embedding_model_name"]
    embedding_text = state["embedding_text"]

    content_hash = hashlib.md5(embedding_text.encode("utf-8")).hexdigest()

    job_emb = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).first()

    if not job_emb:
        job_emb = JobEmbedding(
            embedding_id=uuid4(),
            job_id=job_id,
            embedding=vector,
            embedding_model=model_name,
            embedding_dimension=dimension,
            content_hash=content_hash,
            generated_at=datetime.utcnow(),
        )
        db.add(job_emb)
    else:
        job_emb.embedding = vector
        job_emb.embedding_model = model_name
        job_emb.embedding_dimension = dimension
        job_emb.content_hash = content_hash
        job_emb.generated_at = datetime.utcnow()
        job_emb.updated_at = datetime.utcnow()

    db.commit()
    return {}


def update_ai_metadata_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: update_ai_metadata")
    if state.get("errors"):
        return {}

    db = state["db"]
    job_id = state["job_id"]
    ai_summary = state.get("ai_summary")
    extracted = state.get("ai_extracted_metadata") or {}
    keywords = state.get("ai_keywords") or {}

    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        return {"errors": [f"Job not found for ID: {job_id} during metadata update"]}

    job.ai_summary = ai_summary
    job.ai_required_skills = extracted.get("primary_skills", []) + extracted.get("mandatory_skills", [])
    job.ai_required_skills = list(set(job.ai_required_skills))
    
    job.ai_preferred_skills = extracted.get("secondary_skills", []) + extracted.get("nice_to_have_skills", [])
    job.ai_preferred_skills = list(set(job.ai_preferred_skills))

    job.ai_job_category = extracted.get("job_category")
    job.ai_seniority_level = extracted.get("seniority_level")
    
    job.ai_keywords = keywords.get("keywords", [])
    job.ai_must_have_keywords = keywords.get("must_have_keywords", [])
    job.ai_nice_to_have_keywords = keywords.get("nice_to_have_keywords", [])

    job.ai_tools = extracted.get("tools", [])
    
    techs = []
    techs.extend(extracted.get("frameworks", []))
    techs.extend(extracted.get("databases", []))
    techs.extend(extracted.get("cloud_technologies", []))
    job.ai_technologies = list(set(techs))

    job.ai_soft_skills = extracted.get("soft_skills", [])
    job.ai_domain_experience = extracted.get("domain_experience", [])
    job.ai_embedding_status = True
    job.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(job)

    return {}


def should_ask_questions(state: JobWorkflowState) -> str:
    """
    Conditional edge function to determine if we need to ask questions
    or proceed with the normal workflow.
    """
    if state.get("needs_clarification"):
        return "ask_questions"
    return "proceed_workflow"


def should_proceed_after_store(state: JobWorkflowState) -> str:
    """
    Conditional edge function after storing job to determine if we should
    return questions (if clarification needed) or proceed with AI workflow.
    """
    if state.get("needs_clarification"):
        return "return_questions"
    return "proceed_ai"

workflow = StateGraph(JobWorkflowState)

workflow.add_node("validate_input", validate_input_node)
workflow.add_node("check_data_sufficiency", generate_clarifying_questions_node)
workflow.add_node("store_job", store_job_node)
workflow.add_node("generate_ai_summary", generate_ai_summary_node)
workflow.add_node("extract_skills", extract_skills_node)
workflow.add_node("generate_keywords", generate_searchable_keywords_node)
workflow.add_node("create_embedding_text", create_embedding_text_node)
workflow.add_node("generate_embedding", generate_embedding_node)
workflow.add_node("store_vector", store_vector_node)
workflow.add_node("update_ai_metadata", update_ai_metadata_node)

workflow.add_edge(START, "validate_input")
workflow.add_edge("validate_input", "check_data_sufficiency")

workflow.add_conditional_edges(
    "check_data_sufficiency",
    should_ask_questions,
    {
        "ask_questions": "store_job",
        "proceed_workflow": "store_job"
    }
)

workflow.add_conditional_edges(
    "store_job",
    should_proceed_after_store,
    {
        "return_questions": END,
        "proceed_ai": "generate_ai_summary"
    }
)
workflow.add_edge("generate_ai_summary", "extract_skills")
workflow.add_edge("extract_skills", "generate_keywords")
workflow.add_edge("generate_keywords", "create_embedding_text")
workflow.add_edge("create_embedding_text", "generate_embedding")
workflow.add_edge("generate_embedding", "store_vector")
workflow.add_edge("store_vector", "update_ai_metadata")
workflow.add_edge("update_ai_metadata", END)

job_workflow = workflow.compile()
