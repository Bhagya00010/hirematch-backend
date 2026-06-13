"""Add detailed ATS score breakdown fields to MatchResult

Revision ID: add_ats_score_breakdown
Revises: 71c8b3a9823b
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_ats_score_breakdown'
down_revision = '71c8b3a9823b'
branch_labels = None
depends_on = None


def upgrade():
    # Add new score breakdown fields to match_results table if they don't exist
    from sqlalchemy import inspect
    
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('match_results')]
    
    if 'score_relevant_tech_experience' not in columns:
        op.add_column('match_results', sa.Column('score_relevant_tech_experience', sa.Numeric(5, 2), nullable=True))
    
    if 'score_project' not in columns:
        op.add_column('match_results', sa.Column('score_project', sa.Numeric(5, 2), nullable=True))
    
    if 'score_certification' not in columns:
        op.add_column('match_results', sa.Column('score_certification', sa.Numeric(5, 2), nullable=True))
    
    if 'score_hybrid' not in columns:
        op.add_column('match_results', sa.Column('score_hybrid', sa.Numeric(5, 2), nullable=True))


def downgrade():
    # Remove the new fields
    op.drop_column('match_results', 'score_hybrid')
    op.drop_column('match_results', 'score_certification')
    op.drop_column('match_results', 'score_project')
    op.drop_column('match_results', 'score_relevant_tech_experience')
