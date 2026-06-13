"""Add explainability fields to MatchResult

Revision ID: add_explainability_fields
Revises: add_skill_score
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'add_explainability_fields'
down_revision = 'add_skill_score'
branch_labels = None
depends_on = None


def upgrade():
    # Add explainability fields to match_results table if they don't exist
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('match_results')]
    
    if 'matched_skills' not in columns:
        op.add_column('match_results', sa.Column('matched_skills', sa.ARRAY(sa.Text), nullable=True))
    
    if 'missing_skills' not in columns:
        op.add_column('match_results', sa.Column('missing_skills', sa.ARRAY(sa.Text), nullable=True))
    
    if 'matched_tech_stack' not in columns:
        op.add_column('match_results', sa.Column('matched_tech_stack', sa.ARRAY(sa.Text), nullable=True))
    
    if 'missing_tech_stack' not in columns:
        op.add_column('match_results', sa.Column('missing_tech_stack', sa.ARRAY(sa.Text), nullable=True))


def downgrade():
    # Remove the explainability fields
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('match_results')]
    
    if 'matched_tech_stack' in columns:
        op.drop_column('match_results', 'matched_tech_stack')
    
    if 'missing_tech_stack' in columns:
        op.drop_column('match_results', 'missing_tech_stack')
    
    if 'matched_skills' in columns:
        op.drop_column('match_results', 'matched_skills')
    
    if 'missing_skills' in columns:
        op.drop_column('match_results', 'missing_skills')
