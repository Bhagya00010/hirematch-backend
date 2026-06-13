"""Add skill_tiers column to jobs table

Revision ID: add_skill_tiers
Revises: add_explainability_fields
Create Date: 2026-06-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'add_skill_tiers'
down_revision = 'add_explainability_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Add skill_tiers field to jobs table if it doesn't exist
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('jobs')]
    
    if 'skill_tiers' not in columns:
        op.add_column('jobs', sa.Column('skill_tiers', sa.JSON(), nullable=True))


def downgrade():
    # Remove the skill_tiers field
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('jobs')]
    
    if 'skill_tiers' in columns:
        op.drop_column('jobs', 'skill_tiers')
