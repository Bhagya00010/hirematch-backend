"""Add skill_score field to MatchResult

Revision ID: add_skill_score
Revises: add_ats_score_breakdown
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'add_skill_score'
down_revision = 'add_ats_score_breakdown'
branch_labels = None
depends_on = None


def upgrade():
    # Add skill_score field to match_results table if it doesn't exist
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('match_results')]
    
    if 'score_skill' not in columns:
        op.add_column('match_results', sa.Column('score_skill', sa.Numeric(5, 2), nullable=True))


def downgrade():
    # Remove the skill_score field
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('match_results')]
    
    if 'score_skill' in columns:
        op.drop_column('match_results', 'score_skill')
