from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.models.job import Job, JobStatus


def get_dashboard_data(
    db: Session,
    skip: int = 0,
    limit: int = 10
):
    total_jobs = db.query(func.count(Job.job_id)).scalar()

    active_jobs = (
        db.query(func.count(Job.job_id))
        .filter(Job.status == JobStatus.ACTIVE)
        .scalar()
    )

    closed_jobs = (
        db.query(func.count(Job.job_id))
        .filter(Job.status == JobStatus.CLOSED)
        .scalar()
    )

    draft_jobs = (
        db.query(func.count(Job.job_id))
        .filter(Job.status == JobStatus.DRAFT)
        .scalar()
    )

    parsed_jobs = (
        db.query(func.count(Job.job_id))
        .filter(Job.ai_summary.isnot(None))
        .scalar()
    )

    unparsed_jobs = (
        db.query(func.count(Job.job_id))
        .filter(Job.ai_summary.is_(None))
        .scalar()
    )

    top_roles = (
        db.query(
            Job.job_title,
            func.count(Job.job_id).label("count")
        )
        .group_by(Job.job_title)
        .order_by(func.count(Job.job_id).desc())
        .limit(5)
        .all()
    )

    parsing_stats = (
        db.query(
            Job.job_title,

            func.sum(
                case(
                    (Job.ai_summary.isnot(None), 1),
                    else_=0
                )
            ).label("parsed_count"),

            func.sum(
                case(
                    (Job.ai_summary.is_(None), 1),
                    else_=0
                )
            ).label("unparsed_count")
        )
        .group_by(Job.job_title)
        .all()
    )

    recent_jobs = (
        db.query(Job)
        .order_by(Job.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "stats": {
            "total_jobs": total_jobs,
            "active_jobs": active_jobs,
            "closed_jobs": closed_jobs,
            "draft_jobs": draft_jobs,
            "parsed_jobs": parsed_jobs,
            "unparsed_jobs": unparsed_jobs,
        },
        "top_roles": [
            {
                "job_title": r.job_title,
                "count": r.count
            }
            for r in top_roles
        ],
        "resume_parsing_stats": [
            {
                "job_title": r.job_title,
                "parsed_count": r.parsed_count,
                "unparsed_count": r.unparsed_count,
            }
            for r in parsing_stats
        ],
        "recent_jobs": [
            {
                "job_id": str(job.job_id),
                "job_title": job.job_title,
                "department": job.department,
                "status": job.status.value,
                "created_at": job.created_at,
            }
            for job in recent_jobs
        ]
    }