"""Remove unused fields and make experience/salary/notice nullable

Revision ID: 001_remove_unused_fields
Revises: 
Create Date: 2026-06-08 13:41:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_remove_unused_fields'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make experience_max nullable
    op.alter_column('jobs', 'experience_max', nullable=True)
    
    # Make salary_max nullable
    op.alter_column('jobs', 'salary_max', nullable=True)
    
    # Make notice_period_max nullable
    op.alter_column('jobs', 'notice_period_max', nullable=True)
    
    # Remove location fields
    op.drop_column('jobs', 'location_country')
    op.drop_column('jobs', 'location_state')
    op.drop_column('jobs', 'location_city')
    
    # Remove unused optional fields
    op.drop_column('jobs', 'benefits')
    op.drop_column('jobs', 'working_hours')
    op.drop_column('jobs', 'shift_details')
    op.drop_column('jobs', 'travel_requirements')
    op.drop_column('jobs', 'relocation_support')
    op.drop_column('jobs', 'visa_sponsorship')
    
    # Remove preferred_skills and ai_preferred_skills
    op.drop_column('jobs', 'preferred_skills')
    op.drop_column('jobs', 'ai_preferred_skills')


def downgrade() -> None:
    # Add back preferred_skills and ai_preferred_skills
    op.add_column('jobs', sa.Column('ai_preferred_skills', sa.ARRAY(sa.Text()), nullable=True))
    op.add_column('jobs', sa.Column('preferred_skills', sa.ARRAY(sa.Text()), nullable=False, server_default='{}'))
    
    # Add back unused optional fields
    op.add_column('jobs', sa.Column('visa_sponsorship', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('jobs', sa.Column('relocation_support', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('jobs', sa.Column('travel_requirements', sa.Text(), nullable=True))
    op.add_column('jobs', sa.Column('shift_details', sa.String(length=100), nullable=True))
    op.add_column('jobs', sa.Column('working_hours', sa.String(length=100), nullable=True))
    op.add_column('jobs', sa.Column('benefits', sa.Text(), nullable=True))
    
    # Add back location fields
    op.add_column('jobs', sa.Column('location_city', sa.String(length=100), nullable=False, server_default=''))
    op.add_column('jobs', sa.Column('location_state', sa.String(length=100), nullable=False, server_default=''))
    op.add_column('jobs', sa.Column('location_country', sa.String(length=100), nullable=False, server_default=''))
    
    # Make notice_period_max not nullable
    op.alter_column('jobs', 'notice_period_max', nullable=False, server_default='30')
    
    # Make salary_max not nullable
    op.alter_column('jobs', 'salary_max', nullable=False, server_default='0.0')
    
    # Make experience_max not nullable
    op.alter_column('jobs', 'experience_max', nullable=False, server_default='10')
