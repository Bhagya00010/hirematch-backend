JOB_FIELDS = [
    {
        "field_name": "department",
        "description": "Department name",
        "default_value": "General",
        "ask_question": False,  
        "prompt_template": "What is the department for this position?",
        "field_type": "string",
        "extraction_prompt": "Extract the department name",
        "required": False,
        "validation_keywords": ["department", "team", "division"]
    },
    {
        "field_name": "responsibilities",
        "description": "Job responsibilities",
        "default_value": "",
        "ask_question": False,  
        "prompt_template": "The job description mentions some responsibilities. Are there any additional specific day-to-day tasks or responsibilities not covered in the description?",
        "field_type": "string",
        "extraction_prompt": "Extract ALL job responsibilities mentioned in the description. Look for phrases like 'responsible for', 'responsibilities include', 'you will', 'key responsibilities', 'duties include', 'day-to-day', 'what you'll do'. Extract the complete list of responsibilities as a comprehensive paragraph.",
        "required": True,
        "validation_keywords": ["responsibility", "responsible for", "duties", "tasks", "you will", "key responsibilities"]
    },
    {
        "field_name": "required_skills",
        "description": "Required skills",
        "default_value": [],
        "ask_question": False,  
        "prompt_template": "What are the required technical skills? (comma-separated)",
        "field_type": "list",
        "extraction_prompt": "Extract the required skills",
        "required": True,
        "validation_keywords": ["skills", "technologies", "proficient in", "experience with", "knowledge of", "required", "expertise"]
    },
    {
        "field_name": "experience_min",
        "description": "Minimum experience in years",
        "default_value": None,
        "ask_question": False,
        "field_type": "integer",
        "extraction_prompt": "Extract the minimum years of experience",
        "required": False,
        "validation_keywords": ["minimum", "min", "at least", "years experience"]
    },
    {
        "field_name": "experience_max",
        "description": "Maximum experience in years",
        "default_value": None,
        "ask_question": False,
        "field_type": "integer",
        "extraction_prompt": "Extract the maximum years of experience",
        "required": False,
        "validation_keywords": ["maximum", "max", "up to", "years experience"]
    },
    {
        "field_name": "education_requirements",
        "description": "Education requirements",
        "default_value": "",
        "ask_question": False,
        "prompt_template": "What are the education requirements for this position?",
        "field_type": "string",
        "extraction_prompt": "Extract the education requirements",
        "required": False,
        "validation_keywords": ["education", "degree", "qualification", "bachelor", "master", "phd"]
    },
    {
        "field_name": "certifications",
        "description": "Required certifications",
        "default_value": [],
        "ask_question": False,
        "field_type": "list",
        "extraction_prompt": "Extract any required certifications",
        "required": False,
        "validation_keywords": ["certification", "certified", "aws", "pmp", "scrum"]
    },
    {
        "field_name": "project_name",
        "description": "Project name",
        "default_value": None,
        "ask_question": False,
        "prompt_template": "What is the project name?",
        "field_type": "string",
        "extraction_prompt": "Extract the project name if mentioned",
        "required": False,
        "validation_keywords": ["project", "product", "application"]
    },
    {
        "field_name": "project_sector",
        "description": "Project sector/industry",
        "default_value": None,
        "ask_question": False,
        "prompt_template": "What is the project sector or industry?",
        "field_type": "string",
        "extraction_prompt": "Extract the project sector or industry",
        "required": False,
        "validation_keywords": ["sector", "industry", "domain", "field"]
    }
]

VALIDATION_SETTINGS = {
    "enabled": True,
    "critical_fields": ["responsibilities", "required_skills"],
    "optional_fields": ["project_name", "project_sector", "experience_min", "experience_max"],
    "ask_questions_on_critical_missing": True,
    "ask_questions_on_optional_missing": False,
    "extraction_confidence_threshold": 0.7,
    "max_clarification_questions": 3
}

AI_SETTINGS = {
    "enabled": True,
    "generate_ai_summary": True,
    "summary_length": "paragraph",  # Options: "1 sentence", "2-3 sentences", "paragraph"
    "extract_from_description": True,
    "extraction_temperature": 0,
    "use_fallback_on_failure": True,
    "fallback_to_simple_extraction": True,
    "use_structured_output": True,
    "response_format": "json"  # Options: "json", "pydantic"
}

WORKFLOW_SETTINGS = {
    # Workflow mode
    "mode": "simplified",  # Options: "simplified", "full", "custom"
    
    # Enable/disable specific workflow steps
    "steps": {
        "validate_input": True,
        "generate_summary": True,
        "store_job": True,
        "create_embedding": True
    },
    
    # Workflow execution
    "continue_on_error": False,
    "log_intermediate_steps": True,
    
    # When to trigger embedding generation
    "embedding_trigger": "after_summary"  # Options: "immediate", "after_summary", "manual"
}

EMBEDDING_SETTINGS = {
    "enabled": True,
    "trigger_after_mandatory_complete": True,
    "trigger_after_extraction": True,
    "trigger_manually": True,
    "include_fields": [
        "job_description",
        "ai_summary",
        "responsibilities",
        "required_skills"
    ],

    "model": "default",
    "dimension": None  
}

PROCESSING_MESSAGES = {
    "analyzing": "Analyzing job description and checking for missing information...",
    "generating_question": "Generating clarifying question...",
    "processing_answer": "Processing your answer and updating job data...",
    "extracting_data": "Extracting additional information from job description...",
    "generating_summary": "Generating AI summary...",
    "extracting_skills": "Extracting skills and keywords...",
    "creating_embedding": "Creating vector embeddings for search...",
    "complete": "Job created successfully!",
    "validation_failed": "Job description validation failed. Please provide required information.",
    "ai_error": "AI processing encountered an error. Please try again."
}

CLARIFICATION_SETTINGS = {
    "enabled": True,
    "strategy": "single_field",  # Options: "single_field", "batch", "smart"
    "templates": {
        "missing_critical": "The job description seems to be missing: {fields}. Please provide these details.",
        "missing_optional": "Would you like to provide additional information about: {fields}?",
        "clarify_field": "Could you please provide more details about {field}?"
    },
    
        "max_questions_per_session": 5,
    "allow_skip": True
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

def get_critical_fields() -> list:
    """Get list of critical fields that must be present"""
    return VALIDATION_SETTINGS.get("critical_fields", [])

def get_optional_fields() -> list:
    """Get list of optional fields"""
    return VALIDATION_SETTINGS.get("optional_fields", [])

def is_field_required(field_name: str) -> bool:
    """Check if a field is required"""
    config = get_field_config(field_name)
    if config:
        return config.get("required", False)
    return False

def get_validation_keywords(field_name: str) -> list:
    """Get validation keywords for a field"""
    config = get_field_config(field_name)
    if config:
        return config.get("validation_keywords", [])
    return []

def is_validation_enabled() -> bool:
    """Check if validation is enabled"""
    return VALIDATION_SETTINGS.get("enabled", True)

def is_ai_enabled() -> bool:
    """Check if AI processing is enabled"""
    return AI_SETTINGS.get("enabled", True)

def is_embedding_enabled() -> bool:
    """Check if embedding generation is enabled"""
    return EMBEDDING_SETTINGS.get("enabled", True)

def get_workflow_mode() -> str:
    """Get current workflow mode"""
    return WORKFLOW_SETTINGS.get("mode", "simplified")

def update_setting(section: str, key: str, value: any) -> bool:
    """
    Update a setting value dynamically.
    Returns True if successful, False otherwise.
    """
    settings_map = {
        "validation": VALIDATION_SETTINGS,
        "ai": AI_SETTINGS,
        "workflow": WORKFLOW_SETTINGS,
        "embedding": EMBEDDING_SETTINGS,
        "clarification": CLARIFICATION_SETTINGS
    }
    
    if section in settings_map:
        settings_map[section][key] = value
        return True
    return False

def get_setting(section: str, key: str, default: any = None) -> any:
    """Get a setting value"""
    settings_map = {
        "validation": VALIDATION_SETTINGS,
        "ai": AI_SETTINGS,
        "workflow": WORKFLOW_SETTINGS,
        "embedding": EMBEDDING_SETTINGS,
        "clarification": CLARIFICATION_SETTINGS
    }
    
    if section in settings_map:
        return settings_map[section].get(key, default)
    return default
