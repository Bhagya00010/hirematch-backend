"""Add Full Text Search indexes for hybrid search

Revision ID: 71c8b3a9823b
Revises: 2afc3a541bac
Create Date: 2026-06-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '71c8b3a9823b'
down_revision = '2afc3a541bac'
branch_labels = None
depends_on = None


def upgrade():
    # Add Full Text Search indexes on candidate fields for BM25 search
    op.execute("""
        CREATE INDEX idx_candidates_search_text 
        ON candidates USING gin(
            to_tsvector('english', 
                COALESCE(skills::text, '') || ' ' || 
                COALESCE(tech_stack::text, '') || ' ' || 
                COALESCE(sector_experience::text, '') || ' ' || 
                COALESCE(raw_text, '')
            )
        );
    """)
    
    # Add GIN index on skills array for faster array operations
    op.execute("""
        CREATE INDEX idx_candidates_skills_gin 
        ON candidates USING gin(skills);
    """)
    
    # Add GIN index on tech_stack array
    op.execute("""
        CREATE INDEX idx_candidates_tech_stack_gin 
        ON candidates USING gin(tech_stack);
    """)
    
    # Add GIN index on sector_experience array
    op.execute("""
        CREATE INDEX idx_candidates_sector_experience_gin 
        ON candidates USING gin(sector_experience);
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_candidates_search_text;")
    op.execute("DROP INDEX IF EXISTS idx_candidates_skills_gin;")
    op.execute("DROP INDEX IF EXISTS idx_candidates_tech_stack_gin;")
    op.execute("DROP INDEX IF EXISTS idx_candidates_sector_experience_gin;")
