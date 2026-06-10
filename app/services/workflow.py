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
    get_critical_fields, get_optional_fields, get_validation_keywords,
    is_validation_enabled, is_ai_enabled, is_embedding_enabled,
    get_workflow_mode, VALIDATION_SETTINGS, AI_SETTINGS
)

# Check if LLM supports structured output
STRUCTURED_OUTPUT_AVAILABLE = True

logger = logging.getLogger(__name__)


# Output Model for AI Summary with Output Parser
class JobSummaryOutput(BaseModel):
    """Structured output for job summary"""
    summary: str = Field(description="AI-generated summary of the job")
    responsibilities: List[str] = Field(description="List of responsibilities extracted from job description")
    skills: List[str] = Field(description="List of skills extracted from job description")
    project_name: Optional[str] = Field(description="Project name if mentioned", default=None)
    project_sector: Optional[str] = Field(description="Project sector if mentioned", default=None)
    experience_min: Optional[int] = Field(description="Minimum years of experience", default=None)
    experience_max: Optional[int] = Field(description="Maximum years of experience", default=None)

class JobWorkflowState(TypedDict):
    job_id: Optional[UUID]
    company_id: UUID
    created_by: UUID
    input_data: Dict[str, Any]
    db: Session
    errors: List[str]
    
    # AI Processing Results
    validation_result: Optional[Dict[str, Any]]
    ai_summary_data: Optional[Dict[str, Any]]
    vectordb_id: Optional[str]
    
    needs_clarification: Optional[bool]
    questions: Optional[List[Dict[str, Any]]]


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


def validate_job_input_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    Validate job description input to check for required fields.
    Uses settings from job_settings.py for configuration.
    """
    logger.info("Simplified Workflow Node: validate_job_input")
    
    # Check if validation is enabled
    if not is_validation_enabled():
        logger.info("Validation is disabled, skipping validation")
        return {"validation_result": {"valid": True, "skipped": True}}
    
    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    
    if not job_description:
        return {"errors": ["Job description is required"], "validation_result": {"valid": False}}
    
    validation_result = {
        "valid": True,
        "missing_critical_fields": [],
        "missing_optional_fields": []
    }
    
    # Get critical and optional fields from settings
    critical_fields = get_critical_fields()
    optional_fields = get_optional_fields()
    
    # Check critical fields
    for field_name in critical_fields:
        keywords = get_validation_keywords(field_name)
        has_field = any(keyword.lower() in job_description.lower() for keyword in keywords)
        
        if not has_field:
            validation_result["missing_critical_fields"].append(field_name)
            validation_result["valid"] = False
    
    # Check optional fields
    for field_name in optional_fields:
        keywords = get_validation_keywords(field_name)
        has_field = any(keyword.lower() in job_description.lower() for keyword in keywords)
        
        if not has_field:
            validation_result["missing_optional_fields"].append(field_name)
    
    # Determine if we should ask questions
    ask_questions = False
    questions = []
    
    if validation_result["missing_critical_fields"]:
        if VALIDATION_SETTINGS.get("ask_questions_on_critical_missing", True):
            ask_questions = True
            missing_list = ", ".join(validation_result["missing_critical_fields"])
            questions.append({
                "id": "q1",
                "question": f"The job description seems to be missing critical information: {missing_list}. Please provide these details.",
                "field_name": "job_description"
            })
    
    if validation_result["missing_optional_fields"]:
        if VALIDATION_SETTINGS.get("ask_questions_on_optional_missing", False):
            ask_questions = True
            missing_list = ", ".join(validation_result["missing_optional_fields"])
            questions.append({
                "id": "q2",
                "question": f"The job description is missing optional information: {missing_list}. Would you like to provide these details?",
                "field_name": "job_description"
            })
    
    if ask_questions:
        # Limit number of questions
        max_questions = VALIDATION_SETTINGS.get("max_clarification_questions", 3)
        questions = questions[:max_questions]
        
        return {
            "validation_result": validation_result,
            "needs_clarification": True,
            "questions": questions
        }
    
    return {"validation_result": validation_result}


def generate_ai_summary_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    Generate AI summary using LLM with structured output.
    Uses settings from job_settings.py for configuration.
    """
    logger.info("Simplified Workflow Node: generate_ai_summary")
    
    # Check if AI processing is enabled
    if not is_ai_enabled():
        logger.info("AI processing is disabled, skipping summary generation")
        return {"ai_summary_data": {"summary": "AI summary generation disabled"}}
    
    if state.get("errors"):
        return {}
    
    input_data = state["input_data"]
    job_description = input_data.get('job_description', '')
    job_title = input_data.get('job_title', '')
    
    # Get temperature from settings
    temperature = AI_SETTINGS.get("extraction_temperature", 0.3)
    
    try:
        llm = get_llm(temperature=temperature)
    except Exception as e:
        logger.error(f"Failed to load LLM: {e}")
        return {"errors": [f"LLM Provider Error: {e}"]}
    
    # Get summary length from settings
    summary_length = AI_SETTINGS.get("summary_length", "2-3 sentences")
    
    # Use structured output if enabled in settings
    if STRUCTURED_OUTPUT_AVAILABLE and AI_SETTINGS.get("use_structured_output", True):
        try:
            logger.info("Using with_structured_output approach")
            structured_llm = llm.with_structured_output(JobSummaryOutput)
            
            user_message = f"""Analyze this job description and extract key information:

Job Title: {job_title}
Job Description: {job_description}

Extract:
1. A comprehensive AI summary ({summary_length}) describing the role
2. List of responsibilities mentioned in the job description
3. List of skills/technologies required
4. Project name (if mentioned)
5. Project sector/industry (if mentioned)
6. Minimum years of experience (if specified)
7. Maximum years of experience (if specified)"""
            
            structured_response = structured_llm.invoke(user_message)
            
            if structured_response:
                ai_summary_data = {
                    "summary": structured_response.summary,
                    "responsibilities": structured_response.responsibilities,
                    "skills": structured_response.skills,
                    "project_name": structured_response.project_name,
                    "project_sector": structured_response.project_sector,
                    "experience_min": structured_response.experience_min,
                    "experience_max": structured_response.experience_max
                }
                logger.info(f"AI summary generated with structured output: {ai_summary_data.get('summary', '')[:100]}...")
                return {"ai_summary_data": ai_summary_data}
            else:
                logger.warning("Structured output returned no response, falling back to JSON approach")
                
        except Exception as e:
            logger.error(f"Structured output approach failed: {e}, falling back to JSON approach")
    
    # Fallback: Simple JSON approach
    logger.info("Using fallback JSON approach")
    prompt = f"""You are an expert recruitment AI. Analyze the following job description and extract key information.

Job Title: {job_title}
Job Description: {job_description}

Extract the following information:
1. A comprehensive AI summary ({summary_length}) describing the role
2. List of responsibilities mentioned in the job description
3. List of skills/technologies required
4. Project name (if mentioned)
5. Project sector/industry (if mentioned)
6. Minimum years of experience (if specified)
7. Maximum years of experience (if specified)

Return a JSON object with this exact structure:
{{
  "summary": "{summary_length} summary of the role",
  "responsibilities": ["responsibility 1", "responsibility 2"],
  "skills": ["skill 1", "skill 2"],
  "project_name": "project name or null",
  "project_sector": "sector or null",
  "experience_min": number or null,
  "experience_max": number or null
}}

Be thorough and extract ALL information present in the description.
Output ONLY valid JSON. Do not write any introduction, markdown wrapping, or explanations."""
    
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)
        
        # Clean and parse JSON
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        ai_summary_data = json.loads(text)
        logger.info(f"AI summary generated with fallback: {ai_summary_data.get('summary', '')[:100]}...")
        return {"ai_summary_data": ai_summary_data}
        
    except Exception as e:
        logger.error(f"Error generating AI summary: {e}")
        
        # Check if fallback is enabled
        if AI_SETTINGS.get("use_fallback_on_failure", True):
            logger.warning("AI summary generation failed, returning empty summary")
            return {"ai_summary_data": {"summary": "", "responsibilities": [], "skills": [], "project_name": None, "project_sector": None, "experience_min": None, "experience_max": None}}
        else:
            return {"errors": [f"AI Summary Generation failed: {e}"]}


def store_simplified_job_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    Store job in database with only essential fields:
    - job_id
    - job_description (required)
    - job_title (optional if provided)
    - summary_id (will be the same as job_id for now)
    - created_at
    - ai_summary
    - vectordb_id (will be set when embedding is created)
    """
    logger.info("Simplified Workflow Node: store_simplified_job")
    
    if state.get("errors"):
        return {}
    
    db = state["db"]
    input_data = state["input_data"]
    ai_summary_data = state.get("ai_summary_data", {})
    
    job_id = state.get("job_id") or uuid4()
    
    try:
        # Check if job already exists
        existing_job = db.query(Job).filter(Job.job_id == job_id).first()
        
        if existing_job:
            # Update existing job
            existing_job.job_description = input_data.get('job_description')
            if input_data.get('job_title'):
                existing_job.job_title = input_data.get('job_title')
            existing_job.ai_summary = ai_summary_data.get('summary')
            existing_job.updated_at = datetime.utcnow()
            
            logger.info(f"Updated existing job: {job_id}")
        else:
            # Create new job with only essential fields
            job = Job(
                job_id=job_id,
                company_id=state["company_id"],
                created_by=state["created_by"],
                job_description=input_data.get('job_description'),
                job_title=input_data.get('job_title') or 'Untitled Position',
                job_code='AUTO-' + str(job_id)[:8],  # Auto-generate job code
                department='General',  # Default department
                responsibilities=ai_summary_data.get('summary', ''),  # Store summary in responsibilities for now
                required_skills=ai_summary_data.get('skills', []),
                education_requirements='',  # Empty for now
                certifications=[],
                experience_min=ai_summary_data.get('experience_min'),
                experience_max=ai_summary_data.get('experience_max'),
                ai_summary=ai_summary_data.get('summary'),
                ai_embedding_status=False
            )
            
            db.add(job)
            logger.info(f"Created new job: {job_id}")
        
        db.commit()
        db.refresh(existing_job if existing_job else job)
        
        return {"job_id": job_id}
        
    except Exception as e:
        logger.error(f"Error storing job: {e}")
        db.rollback()
        return {"errors": [f"Job Storage failed: {e}"]}


def create_embedding_node(state: JobWorkflowState) -> Dict[str, Any]:
    """
    Create embedding for the job and store vectordb_id.
    Uses settings from job_settings.py for configuration.
    """
    logger.info("Simplified Workflow Node: create_embedding")
    
    # Check if embedding generation is enabled
    if not is_embedding_enabled():
        logger.info("Embedding generation is disabled, skipping")
        return {"vectordb_id": None}
    
    if state.get("errors"):
        return {}
    
    job_id = state.get("job_id")
    if not job_id:
        return {"errors": ["No job_id available for embedding"]}
    
    db = state["db"]
    ai_summary_data = state.get("ai_summary_data", {})
    
    # Combine job description and AI summary for embedding
    embedding_text = f"""
    Job Description: {state["input_data"].get('job_description')}
    AI Summary: {ai_summary_data.get('summary', '')}
    Responsibilities: {', '.join(ai_summary_data.get('responsibilities', []))}
    Skills: {', '.join(ai_summary_data.get('skills', []))}
    """
    
    try:
        embeddings_client = get_embeddings()
        
        vector = embeddings_client.embed_query(embedding_text)
        dimension = len(vector)
        
        # Store embedding in job_embeddings table
        content_hash = hashlib.md5(embedding_text.encode("utf-8")).hexdigest()
        
        # Check if embedding already exists
        existing_emb = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).first()
        
        if existing_emb:
            existing_emb.embedding = vector
            existing_emb.embedding_dimension = dimension
            existing_emb.content_hash = content_hash
            existing_emb.updated_at = datetime.utcnow()
            vectordb_id = str(existing_emb.embedding_id)
        else:
            job_emb = JobEmbedding(
                embedding_id=uuid4(),
                job_id=job_id,
                embedding=vector,
                embedding_model="default",
                embedding_dimension=dimension,
                content_hash=content_hash
            )
            db.add(job_emb)
            vectordb_id = str(job_emb.embedding_id)
        
        # Update job's embedding status
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if job:
            job.ai_embedding_status = True
            job.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"Embedding created and stored: {vectordb_id}")
        return {"vectordb_id": vectordb_id}
        
    except Exception as e:
        logger.error(f"Error creating embedding: {e}")
        return {"errors": [f"Embedding Creation failed: {e}"]}


def should_proceed(state: JobWorkflowState) -> str:
    """Determine if workflow should proceed or stop due to errors"""
    if state.get("errors"):
        return "stop"
    if state.get("needs_clarification"):
        return "ask_questions"
    return "proceed"


# Build the simplified workflow graph
def build_simplified_workflow() -> StateGraph:
    """Build and return the simplified job processing workflow"""
    
    workflow = StateGraph(JobWorkflowState)
    
    # Add nodes
    workflow.add_node("validate_input", validate_job_input_node)
    workflow.add_node("generate_summary", generate_ai_summary_node)
    workflow.add_node("store_job", store_simplified_job_node)
    workflow.add_node("create_embedding", create_embedding_node)
    
    # Define edges
    workflow.add_edge(START, "validate_input")
    
    # Conditional edge after validation
    workflow.add_conditional_edges(
        "validate_input",
        should_proceed,
        {
            "ask_questions": END,
            "proceed": "generate_summary",
            "stop": END
        }
    )
    
    workflow.add_edge("generate_summary", "store_job")
    workflow.add_edge("store_job", "create_embedding")
    workflow.add_edge("create_embedding", END)
    
    return workflow


# Create the workflow instance
job_workflow = build_simplified_workflow().compile()
