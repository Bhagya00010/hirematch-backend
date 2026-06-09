JOB_FIELDS = [
    {
        "field_name": "department",
        "description": "Department name",
        "default_value": "Engineering",
        "ask_question": True,
        "prompt_template": "What is the department for this position?",
        "field_type": "string",
        "extraction_prompt": "Extract the department name"
    },
    {
        "field_name": "responsibilities",
        "description": "Job responsibilities",
        "default_value": "",
        "ask_question": True,
        "prompt_template": "The job description mentions some responsibilities. Are there any additional specific day-to-day tasks or responsibilities not covered in the description?",
        "field_type": "string",
        "extraction_prompt": "Extract ALL job responsibilities mentioned in the description. Look for phrases like 'responsible for', 'responsibilities include', 'you will', 'key responsibilities', 'duties include', 'day-to-day', 'what you'll do'. Extract the complete list of responsibilities as a comprehensive paragraph."
    },
    {
        "field_name": "required_skills",
        "description": "Required skills",
        "default_value": [],
        "ask_question": True,
        "prompt_template": "What are the required technical skills? (comma-separated)",
        "field_type": "list",
        "extraction_prompt": "Extract the required skills"
    },
    {
        "field_name": "experience_min",
        "description": "Minimum experience in years",
        "default_value": 0,
        "ask_question": False,
        "field_type": "integer",
        "extraction_prompt": "Extract the minimum years of experience"
    },
    {
        "field_name": "experience_max",
        "description": "Maximum experience in years",
        "default_value": None,
        "ask_question": False,
        "field_type": "integer",
        "extraction_prompt": "Extract the maximum years of experience"
    },
    {
        "field_name": "education_requirements",
        "description": "Education requirements",
        "default_value": "",
        "ask_question": True,
        "prompt_template": "What are the education requirements for this position?",
        "field_type": "string",
        "extraction_prompt": "Extract the education requirements"
    },
    {
        "field_name": "certifications",
        "description": "Required certifications",
        "default_value": [],
        "ask_question": False,
        "field_type": "list",
        "extraction_prompt": "Extract any required certifications"
    }
]

PROCESSING_MESSAGES = {
    "analyzing": "Analyzing job description and checking for missing information...",
    "generating_question": "Generating clarifying question...",
    "processing_answer": "Processing your answer and updating job data...",
    "extracting_data": "Extracting additional information from job description...",
    "generating_summary": "Generating AI summary...",
    "extracting_skills": "Extracting skills and keywords...",
    "creating_embedding": "Creating vector embeddings for search...",
    "complete": "Job created successfully!"
}

EMBEDDING_SETTINGS = {
    "trigger_after_mandatory_complete": True,  
    "trigger_after_extraction": True,  
    "trigger_manually": True  
}

def get_field_config(field_name: str) -> dict:
    """Get configuration for a specific field"""
    for field in JOB_FIELDS:
        if field["field_name"] == field_name:
            return field
    return None

def get_default_value(field_name: str) -> any:
    """Get default value for a field"""
    config = get_field_config(field_name)
    if config:
        return config["default_value"]
    return None

def get_fields_to_ask() -> list:
    """Get list of fields that should be asked to user (ask_question=True)"""
    return [field for field in JOB_FIELDS if field.get("ask_question", False)]

def get_all_fields() -> list:
    """Get all fields"""
    return JOB_FIELDS
