import json
import hashlib
import logging
import re
from typing import TypedDict, List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime
import enum

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, START, END

from app.core.llm import get_llm, get_embeddings
from app.models.job import Job, JobEmbedding, JobStatus

logger = logging.getLogger(__name__)


def extract_all_fields_common_fallback(job_description: str, job_title: str = "") -> Dict[str, Any]:
    """
    Common AI-based fallback function to extract all missing fields dynamically.
    Replaces separate regex-based fallback functions with a single AI prompt.
    """
    if not job_description:
        return {}
    
    try:
        llm = get_llm(temperature=0.1)
    except Exception as e:
        logger.error(f"Failed to load LLM in common fallback: {e}")
        return {}
    
    prompt = f"""You are an expert recruitment AI. Extract the following information from the job description.

Job Title: {job_title}
Job Description: {job_description}

Extract these fields if present in the text:
- job_title: The role name (e.g., "Machine Learning Engineer", "Senior Developer", "Product Manager")
- responsibilities: Main duties and responsibilities as a single string

CRITICAL INSTRUCTIONS:
1. Look ANYWHERE in the text for the role name - beginning, end, middle
2. Be EXTREMELY AGGRESSIVE in extraction - if you see ANY hint of information, extract it
3. For responsibilities: extract ALL sentences describing work, even if not explicitly labeled
4. Look for patterns like "responsible for", "duties", "tasks", "you will", "key responsibilities"
5. Handle informal language, typos, and variations intelligently
6. Better to extract something than nothing

Return a JSON object with the field names as keys. If a field truly cannot be found, set it to null.

Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations.
"""
    
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        extracted_data = parse_json_response(text)
        logger.info(f"Common AI fallback extracted: {list(extracted_data.keys())}")
        return extracted_data
    except Exception as e:
        logger.error(f"Error in common AI fallback: {e}")
        return {}

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


def extract_missing_fields_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    Use AI to extract missing fields from job_description before asking questions.
    This improves accuracy by attempting to extract information from the text first.
    """
    logger.info("LangGraph Node: extract_missing_fields")
    
    from app.core.job_settings import get_fields_to_ask, get_field_config
    
    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    job_title = input_data.get('job_title', '')
    
    if not job_description:
        return {"input_data": input_data}
    
    fields_to_ask = get_fields_to_ask()
    missing_fields = []
    
    for field_config in fields_to_ask:
        field_name = field_config["field_name"]
        value = input_data.get(field_name)
        if is_insufficient_data(value):
            missing_fields.append((field_name, field_config))
    
    if is_insufficient_data(job_title) and job_description:
        missing_fields.append(("job_title", {"field_name": "job_title", "description": "Job title/role", "field_type": "string", "extraction_prompt": "Extract the job title or role name"}))
    
    if not missing_fields:
        return {"input_data": input_data}
    
    try:
        llm = get_llm(temperature=0.1)
    except Exception as e:
        logger.error(f"Failed to load LLM in extract_missing_fields: {e}")
        return {"input_data": input_data}
    
    field_descriptions = []
    for field_name, field_config in missing_fields:
        extraction_prompt = field_config.get("extraction_prompt", f"Extract the {field_config['description'].lower()}")
        field_type = field_config.get("field_type", "string")
        field_descriptions.append(f"- {field_name} ({field_type}): {extraction_prompt}")
    
    prompt = f"""You are an expert recruitment AI. Extract the following information from the job description and title.

Job Title: {job_title}
Job Description: {job_description}

Extract the following fields if present in the text:
{chr(10).join(field_descriptions)}

CRITICAL INSTRUCTIONS - READ CAREFULLY:

1. **job_title**: Look ANYWHERE in the text for the role name. Common patterns:
   - "We are looking for a [ROLE]"
   - "Hiring a [ROLE]"
   - "Position: [ROLE]"
   - "Role: [ROLE]"
   - "[ROLE] needed"
   - "Apply for [ROLE]"
   - The role mentioned at the beginning or end of description
   - Examples: "Machine Learning Engineer", "Senior Developer", "Product Manager", "Data Scientist", "Frontend Developer"

2. **responsibilities**: Look for ANY text describing what the person will do:
   - "responsible for", "responsibilities", "duties", "tasks"
   - "You will", "Your role", "Key responsibilities"
   - "What you'll do", "Day-to-day"
   - Sentences with action verbs (design, develop, build, create, manage, lead)
   - Extract ALL responsibilities as a comprehensive single string
   - If multiple sentences, combine them into one paragraph
   - Look for patterns like "include [list of tasks]" and extract the entire list

3. **required_skills**: Look for ANY technical skills mentioned:
   - "skills", "technologies", "proficient in", "experience with"
   - "knowledge of", "must have", "required", "expertise in"
   - Programming languages, frameworks, tools, databases
   - Extract as comma-separated list
   - Include ALL technical terms mentioned even if not explicitly labeled as skills

4. **education_requirements**: Look for:
   - "Education:" or "Qualifications:" or "Requirements:"
   - "Bachelor's degree", "Master's degree", "PhD"
   - "Degree in [field]"
   - "Educational requirements"
   - Extract as a single string

5. **department**: Look for department/team information:
   - "department", "team", "join our"
   - Common departments: Engineering, Marketing, Sales, Product, Design, etc.
   - Look for phrases like "Engineering team", "join our [department] team"
   - Extract the department name

6. **experience_min**: Look for:
   - "X+ years experience", "Minimum X years", "At least X years"
   - "X years of experience required"
   - Extract as integer (number only)

7. **experience_max**: Look for:
   - "Up to X years", "Maximum X years"
   - "X-Y years experience" (extract Y)
   - Extract as integer (number only)

8. **certifications**: Look for:
   - "Certifications:", "Required certifications:"
   - Specific certification names (e.g., "AWS", "PMP", "Scrum")
   - Extract as comma-separated list

MOST IMPORTANT:
- Be EXTREMELY AGGRESSIVE in extraction
- If you see ANY hint of information, EXTRACT IT
- The job description may be informal - extract intelligently
- For responsibilities: extract ALL sentences describing work, combine into comprehensive paragraph
- For skills: extract ALL technical terms mentioned
- If information is clearly present but not in exact format, still extract it
- Better to extract something than nothing
- Only set field to null if information is truly absent

Return a JSON object with the field names as keys. For list fields, return an array of strings.
For numeric fields (experience_min, experience_max), return numbers only.
If a field truly cannot be found, set it to null - but only as a last resort.

Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations.
"""
    
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"LLM extraction response: {text[:500]}...")
        extracted_data = parse_json_response(text)
        logger.info(f"Parsed extracted data: {extracted_data}")
        
        # Update input_data with extracted values
        updated_input_data = input_data.copy()
        for field_name, value in extracted_data.items():
            if value is not None and not is_insufficient_data(value):
                # Handle enum values
                field_config = get_field_config(field_name)
                if field_config and field_config.get("field_type") == "enum":
                    allowed_values = field_config.get("allowed_values", [])
                    if isinstance(value, str):
                        # Try to match case-insensitively for enum values
                        for allowed in allowed_values:
                            if allowed.lower() == value.lower():
                                updated_input_data[field_name] = allowed
                                logger.info(f"Matched enum {field_name}: {value} -> {allowed}")
                                break
                        else:
                            # Keep original if no match
                            if value in allowed_values:
                                updated_input_data[field_name] = value
                                logger.info(f"Enum {field_name} already valid: {value}")
                else:
                    updated_input_data[field_name] = value
                    logger.info(f"Extracted {field_name}: {value}")
        
        logger.info(f"Final extracted fields: {list(extracted_data.keys())}")
        logger.info(f"Updated input_data keys: {list(updated_input_data.keys())}")
        
        # Fallback: If any fields are still missing, try common AI extraction
        missing_fields = ["job_title", "responsibilities"]
        if any(is_insufficient_data(updated_input_data.get(field)) for field in missing_fields) and job_description:
            logger.info("AI extraction failed for some fields, trying common AI fallback")
            fallback_data = extract_all_fields_common_fallback(job_description, job_title)
            for field_name, value in fallback_data.items():
                if value and not is_insufficient_data(value):
                    updated_input_data[field_name] = value
                    logger.info(f"Successfully extracted {field_name} using common fallback: {value}")
        
        return {"input_data": updated_input_data}
        
    except Exception as e:
        logger.error(f"Error invoking LLM in extract_missing_fields: {e}")
        logger.error(f"LLM response was: {text if 'text' in locals() else 'N/A'}")
        
        # Fallback: Try common AI extraction even if AI failed completely
        missing_fields = ["job_title", "responsibilities"]
        if any(is_insufficient_data(input_data.get(field)) for field in missing_fields) and job_description:
            logger.info("AI extraction failed completely, trying common AI fallback")
            fallback_data = extract_all_fields_common_fallback(job_description, job_title)
            for field_name, value in fallback_data.items():
                if value and not is_insufficient_data(value):
                    input_data[field_name] = value
                    logger.info(f"Successfully extracted {field_name} using common fallback after AI failure: {value}")
        
        return {"input_data": input_data}

def validate_input_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: validate_input")
    input_data = state.get("input_data", {})
    errors = []

    if not input_data.get("job_description"):
        errors.append("job_description is required")
    
    if not input_data.get("job_title"):
        logger.info("job_title missing, will attempt extraction from description")

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
        
        job_title = input_data.get("job_title")
        job_description = input_data.get("job_description", "")
        if not job_title or is_insufficient_data(job_title):
            logger.warning("job_title missing after extraction, trying common AI fallback")
            fallback_data = extract_all_fields_common_fallback(job_description, job_title)
            fallback_title = fallback_data.get("job_title")
            if fallback_title and not is_insufficient_data(fallback_title):
                job_title = fallback_title
                logger.info(f"Successfully extracted job_title using common fallback in store_job: {fallback_title}")
            else:
                job_title = "Untitled Position"
                logger.warning("job_title still missing after fallback, using placeholder")
        
        job_data = {
            "job_id": job_id or uuid4(),
            "company_id": state["company_id"],
            "created_by": state["created_by"],
            "job_title": job_title,
            "job_code": input_data.get("job_code", ""),
            "vacancies": input_data.get("vacancies", 1),
            "job_description": input_data["job_description"],
            "status": status,
            "industry": input_data.get("industry"),
            "team_name": input_data.get("team_name"),
            "project_name": input_data.get("project_name"),
            "internal_notes": input_data.get("internal_notes"),
        }
        
        for field_config in get_all_fields():
            field_name = field_config["field_name"]
            if field_name not in ["experience_max"]:
                job_data[field_name] = input_data.get(field_name, field_config["default_value"])
        
        # Handle experience logic for new job creation
        experience_min = input_data.get("experience_min")
        experience_max = input_data.get("experience_max")
        if experience_min is not None and experience_max is None:
            # Only min provided, keep max as null
            job_data["experience_min"] = experience_min
            job_data["experience_max"] = None
        elif experience_max is not None and experience_min is None:
            # Only max provided, min can default to 0
            job_data["experience_min"] = 0
            job_data["experience_max"] = experience_max
        else:
            # Both provided or both null
            job_data["experience_min"] = experience_min if experience_min is not None else 0
            job_data["experience_max"] = experience_max if experience_max is not None else None
        
        job = Job(**job_data)
        db.add(job)
    else:
        job.job_title = input_data["job_title"]
        job.job_code = input_data["job_code"]
        job.department = input_data["department"]
        
        # Handle experience logic: if only min provided, max should be null. If only max provided, min can default to 0
        experience_min = input_data.get("experience_min")
        experience_max = input_data.get("experience_max")
        if experience_min is not None and experience_max is None:
            # Only min provided, keep max as null
            job.experience_min = experience_min
            job.experience_max = None
        elif experience_max is not None and experience_min is None:
            # Only max provided, min can default to 0
            job.experience_min = 0
            job.experience_max = experience_max
        else:
            # Both provided or both null
            job.experience_min = experience_min if experience_min is not None else job.experience_min
            job.experience_max = experience_max if experience_max is not None else job.experience_max
        
        job.vacancies = input_data.get("vacancies", job.vacancies)
        job.job_description = input_data["job_description"]
        job.responsibilities = input_data["responsibilities"]
        job.required_skills = input_data.get("required_skills", job.required_skills)
        job.education_requirements = input_data["education_requirements"]
        job.certifications = input_data.get("certifications", job.certifications)
        job.status = status
        
        for field in [
            "industry", "team_name", "project_name", "internal_notes"
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

    prompt = f"""You are an expert recruitment AI analyst. Perform a deep analysis of this job posting and create a comprehensive summary that captures the essence of the role.

Job Title: {input_data.get('job_title')}
Department: {input_data.get('department')}
Description: {input_data.get('job_description')}
Responsibilities: {input_data.get('responsibilities')}
Required Skills: {', '.join(input_data.get('required_skills', []))}
Education Requirements: {input_data.get('education_requirements')}
Experience: {input_data.get('experience_min')} to {input_data.get('experience_max')} years

ANALYSIS INSTRUCTIONS:
1. Understand the core purpose of this role - what problems will this person solve?
2. Identify the key technical domains and expertise areas required
3. Understand the level of seniority and responsibility
4. Capture the unique aspects that make this role specific
5. Note any specialized knowledge, tools, or methodologies

Create a 3-4 sentence summary that:
- Describes the role's core function and impact
- Highlights the primary technical domains and expertise
- Indicates the seniority level and key responsibilities
- Mentions critical technologies or methodologies

Example Summary:
"Senior Backend Engineer responsible for designing and implementing scalable microservices architecture using Python, FastAPI, and PostgreSQL. Role requires 3-5 years of experience in distributed systems, with expertise in REST APIs, Docker containerization, and cloud deployment on AWS. Will lead technical decisions for high-traffic systems and mentor junior developers on best practices."

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

    prompt = f"""You are an expert recruitment AI analyst. Perform a deep semantic analysis of this job posting to extract comprehensive skills and role understanding.

Job Title: {input_data.get('job_title')}
Department: {input_data.get('department')}
Description: {input_data.get('job_description')}
Responsibilities: {input_data.get('responsibilities')}
Education Requirements: {input_data.get('education_requirements')}
Certifications: {', '.join(input_data.get('certifications', []))}
Required Skills: {', '.join(input_data.get('required_skills', []))}
Experience: {input_data.get('experience_min')} to {input_data.get('experience_max')} years

DEEP ANALYSIS INSTRUCTIONS:
1. **Role Responsibility Analysis**: Understand what the person will actually DO day-to-day. Extract skills based on actual tasks, not just keywords.
2. **Technical Depth**: Identify not just skill names, but the depth of knowledge required (e.g., "basic Python" vs "advanced Python with asyncio").
3. **Skill Relationships**: Understand how skills relate to each other - which are foundational vs which are specialized.
4. **Implicit Skills**: Extract skills that are implied by responsibilities even if not explicitly listed.
5. **Domain Context**: Understand the industry/domain context to extract relevant domain-specific skills.

Return a JSON object with the following keys. Values MUST be lists of strings unless specified otherwise:

TECHNICAL SKILLS:
- primary_skills: core technical skills that are absolutely essential for this role
- secondary_skills: supporting technical skills that are important but not deal-breakers
- mandatory_skills: non-negotiable requirements - candidate MUST have these
- nice_to_have_skills: preferred skills that would make a candidate stand out

TECHNOLOGY STACK:
- tools: software tools, IDEs, development tools, productivity tools
- frameworks: libraries, frameworks, SDKs mentioned or implied
- databases: database systems, data stores, caching layers
- cloud_technologies: cloud platforms (AWS, GCP, Azure), services, serverless

SOFT SKILLS & LEADERSHIP:
- soft_skills: interpersonal, communication, collaboration skills
- leadership_skills: management, mentoring, decision-making skills (if applicable)
- problem_solving: analytical, critical thinking, problem-solving approaches

ROLE CONTEXT:
- seniority_level: string (e.g. Junior, Mid, Senior, Lead, Principal, Executive)
- job_category: string (e.g. Engineering, Sales, Product, Marketing, Finance, Data Science)
- role_focus: what this role primarily focuses on (e.g. "backend development", "team management", "client relations")
- team_structure: how this role fits in the team (e.g. "individual contributor", "team lead", "cross-functional collaborator")

REQUIREMENTS:
- education: detailed education requirements (e.g. "Bachelor's in Computer Science or related field")
- certifications: list of required or preferred certifications
- years_experience: range or string (e.g. "3-5 years")
- domain_experience: specific industries or domains (e.g. "fintech", "healthcare", "e-commerce")

IMPLICIT EXTRACTIONS:
- methodologies: development methodologies (Agile, Scrum, Kanban, DevOps practices)
- architectural_concepts: architectural patterns or concepts (microservices, event-driven, monolith)
- performance_expectations: performance, scalability, reliability expectations

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


def analyze_requirements_node(state: JobWorkflowState) -> Dict[str, Any]:
    logger.info("LangGraph Node: analyze_requirements")
    if state.get("errors"):
        return {}

    input_data = state["input_data"]
    extracted = state.get("ai_extracted_metadata") or {}
    
    try:
        llm = get_llm(temperature=0.1)
    except Exception as e:
        logger.error(f"Failed to load LLM in analyze_requirements: {e}")
        return {"errors": [f"LLM Provider Error: {e}"]}

    prompt = f"""You are an expert recruitment analyst. Perform a deep semantic analysis of the job requirements to understand what this role truly needs.

Job Title: {input_data.get('job_title')}
Department: {input_data.get('department')}
Description: {input_data.get('job_description')}
Responsibilities: {input_data.get('responsibilities')}
Required Skills: {', '.join(input_data.get('required_skills', []))}
Education Requirements: {input_data.get('education_requirements')}
Experience: {input_data.get('experience_min')} to {input_data.get('experience_max')} years
Certifications: {', '.join(input_data.get('certifications', []))}

DEEP REQUIREMENTS ANALYSIS:
1. **Understand the "Why"**: Why are these requirements needed? What problems will the candidate solve?
2. **Requirement Hierarchy**: Which requirements are foundational vs which are specialized?
3. **Implicit Requirements**: What requirements are implied but not explicitly stated?
4. **Requirement Flexibility**: Which requirements are negotiable vs non-negotiable?
5. **Contextual Understanding**: How do requirements relate to the actual day-to-day work?

Return a JSON object with the following keys:

REQUIREMENT ANALYSIS:
- core_requirements: the absolute must-have requirements that define this role
- contextual_requirements: requirements that make sense in the specific context of this role
- implicit_requirements: skills/qualities implied by the role but not explicitly listed
- negotiable_requirements: requirements that could be flexible for the right candidate
- deal_breakers: requirements that would immediately disqualify a candidate

REQUIREMENT RELATIONSHIPS:
- prerequisite_skills: skills that are prerequisites for other required skills
- skill_combinations: specific combinations of skills that are valuable together
- complementary_skills: skills that complement each other in this role

REQUIREMENT DEPTH:
- expertise_levels: for each key skill, indicate the depth needed (e.g., "advanced", "intermediate", "basic")
- experience_context: what kind of experience is actually needed (e.g., "hands-on development", "architecture design", "team leadership")
- domain_knowledge: specific domain knowledge required (e.g., "fintech regulations", "healthcare compliance")

ROLE SPECIFICS:
- daily_tasks: what the person will actually do day-to-day based on requirements
- success_metrics: what success looks like in this role based on requirements
- challenges: what challenges this person will face based on requirements

Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations.
"""
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        requirements_analysis = parse_json_response(text)
        return {"ai_requirements_analysis": requirements_analysis}
    except Exception as e:
        logger.error(f"Error invoking LLM in analyze_requirements: {e}")
        return {"ai_requirements_analysis": {}}


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
    requirements_analysis = state.get("ai_requirements_analysis") or {}

    req_skills = ", ".join(input_data.get("required_skills") or [])
    certifications = ", ".join(input_data.get("certifications") or [])

    # Enhanced extracted metadata
    ai_primary = ", ".join(extracted.get("primary_skills") or [])
    ai_secondary = ", ".join(extracted.get("secondary_skills") or [])
    ai_mandatory = ", ".join(extracted.get("mandatory_skills") or [])
    ai_nice = ", ".join(extracted.get("nice_to_have_skills") or [])
    ai_tools = ", ".join(extracted.get("tools") or [])
    ai_frameworks = ", ".join(extracted.get("frameworks") or [])
    ai_db = ", ".join(extracted.get("databases") or [])
    ai_cloud = ", ".join(extracted.get("cloud_technologies") or [])
    ai_soft = ", ".join(extracted.get("soft_skills") or [])
    ai_leadership = ", ".join(extracted.get("leadership_skills") or [])
    ai_problem_solving = ", ".join(extracted.get("problem_solving") or [])
    ai_domain = ", ".join(extracted.get("domain_experience") or [])
    ai_methodologies = ", ".join(extracted.get("methodologies") or [])
    ai_architectural = ", ".join(extracted.get("architectural_concepts") or [])
    ai_performance = ", ".join(extracted.get("performance_expectations") or [])

    # Role context
    role_focus = extracted.get("role_focus", "")
    team_structure = extracted.get("team_structure", "")

    # Requirements analysis
    core_reqs = ", ".join(requirements_analysis.get("core_requirements") or [])
    implicit_reqs = ", ".join(requirements_analysis.get("implicit_requirements") or [])
    deal_breakers = ", ".join(requirements_analysis.get("deal_breakers") or [])
    prerequisite_skills = ", ".join(requirements_analysis.get("prerequisite_skills") or [])
    skill_combinations = ", ".join(requirements_analysis.get("skill_combinations") or [])
    daily_tasks = ", ".join(requirements_analysis.get("daily_tasks") or [])
    success_metrics = ", ".join(requirements_analysis.get("success_metrics") or [])
    challenges = ", ".join(requirements_analysis.get("challenges") or [])
    expertise_levels = str(requirements_analysis.get("expertise_levels", {}))
    experience_context = requirements_analysis.get("experience_context", "")
    domain_knowledge = ", ".join(requirements_analysis.get("domain_knowledge") or [])

    # Keywords
    kw_general = ", ".join(keywords.get("keywords") or [])
    kw_must = ", ".join(keywords.get("must_have_keywords") or [])
    kw_nice = ", ".join(keywords.get("nice_to_have_keywords") or [])

    embedding_text = f"""JOB OVERVIEW:
Job Title: {input_data.get('job_title')}
Department: {input_data.get('department')}
Experience Range: {input_data.get('experience_min')} to {input_data.get('experience_max')} years
Seniority Level: {extracted.get('seniority_level', '')}
Job Category: {extracted.get('job_category', '')}
Role Focus: {role_focus}
Team Structure: {team_structure}

CORE JOB INFORMATION:
Required Skills: {req_skills}
Responsibilities: {input_data.get('responsibilities')}
Job Description: {input_data.get('job_description')}
Education Requirements: {input_data.get('education_requirements')}
Certifications: {certifications}

DEEP SKILLS ANALYSIS:
Primary Skills (Essential): {ai_primary}
Secondary Skills (Important): {ai_secondary}
Mandatory Skills (Non-negotiable): {ai_mandatory}
Nice to Have Skills: {ai_nice}

TECHNOLOGY STACK:
Tools: {ai_tools}
Frameworks: {ai_frameworks}
Databases: {ai_db}
Cloud Technologies: {ai_cloud}
Methodologies: {ai_methodologies}
Architectural Concepts: {ai_architectural}
Performance Expectations: {ai_performance}

SOFT SKILLS & LEADERSHIP:
Soft Skills: {ai_soft}
Leadership Skills: {ai_leadership}
Problem Solving Approaches: {ai_problem_solving}

DOMAIN & CONTEXT:
Domain Experience: {ai_domain}
Domain Knowledge: {domain_knowledge}
Experience Context: {experience_context}

REQUIREMENTS ANALYSIS:
Core Requirements: {core_reqs}
Implicit Requirements: {implicit_reqs}
Deal Breakers: {deal_breakers}
Prerequisite Skills: {prerequisite_skills}
Skill Combinations: {skill_combinations}
Expertise Levels: {expertise_levels}

ROLE SPECIFICS:
Daily Tasks: {daily_tasks}
Success Metrics: {success_metrics}
Challenges: {challenges}

SEARCH KEYWORDS:
General Keywords: {kw_general}
Must Have Keywords: {kw_must}
Nice to Have Keywords: {kw_nice}

AI SUMMARY:
{ai_summary}"""

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
workflow.add_node("extract_missing_fields", extract_missing_fields_node)
workflow.add_node("check_data_sufficiency", generate_clarifying_questions_node)
workflow.add_node("store_job", store_job_node)
workflow.add_node("generate_ai_summary", generate_ai_summary_node)
workflow.add_node("extract_skills", extract_skills_node)
workflow.add_node("analyze_requirements", analyze_requirements_node)
workflow.add_node("generate_keywords", generate_searchable_keywords_node)
workflow.add_node("create_embedding_text", create_embedding_text_node)
workflow.add_node("generate_embedding", generate_embedding_node)
workflow.add_node("store_vector", store_vector_node)
workflow.add_node("update_ai_metadata", update_ai_metadata_node)

workflow.add_edge(START, "validate_input")
workflow.add_edge("validate_input", "extract_missing_fields")
workflow.add_edge("extract_missing_fields", "check_data_sufficiency")

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
workflow.add_edge("extract_skills", "analyze_requirements")
workflow.add_edge("analyze_requirements", "generate_keywords")
workflow.add_edge("generate_keywords", "create_embedding_text")
workflow.add_edge("create_embedding_text", "generate_embedding")
workflow.add_edge("generate_embedding", "store_vector")
workflow.add_edge("store_vector", "update_ai_metadata")
workflow.add_edge("update_ai_metadata", END)

job_workflow = workflow.compile()
