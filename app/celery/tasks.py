import hashlib
import logging
from uuid import uuid4
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.celery.celery_app import celery_app
from app.core.llm import get_embeddings
from app.models.job import Job, JobEmbedding
from app.db.session import get_db

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.celery.tasks.create_job_embedding")
def create_job_embedding_task(self, job_id: str) -> dict:
    """
    Celery task to create embedding for a job asynchronously.
    Runs in a separate queue to avoid blocking the main job creation flow.
    """
    db: Optional[Session] = None
    try:
        db = next(get_db())
        
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if not job:
            logger.error(f"Job not found for embedding: {job_id}")
            return {"success": False, "error": "Job not found"}
        
        # Build embedding text
        ai_summary_data = {
            "summary": job.ai_summary or "",
            "responsibilities": job.required_skills or [],  # Using required_skills as fallback
            "skills": job.required_skills or []
        }
        
        parts = [
            job.job_description,
            ai_summary_data.get('summary', ''),
            ' '.join(ai_summary_data.get('responsibilities', [])),
            ' '.join(ai_summary_data.get('skills', []))
        ]
        embedding_text = ' '.join(p for p in parts if p).strip()
        
        # Create embedding
        vector = get_embeddings().embed_query(embedding_text)
        dimension = len(vector)
        content_hash = hashlib.md5(embedding_text.encode()).hexdigest()
        
        # Store or update embedding
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
        
        # Update job embedding status
        job.ai_embedding_status = True
        job.updated_at = datetime.utcnow()
        
        db.commit()
        logger.info(f"Embedding created asynchronously for job: {job_id}")
        
        return {"success": True, "vectordb_id": vectordb_id, "job_id": job_id}
        
    except Exception as e:
        logger.error(f"Error creating embedding for job {job_id}: {e}")
        if db:
            db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if db:
            db.close()
