"""add recall category and demographics

Revision ID: b4e92a7d3c61
Revises: 8fb3a4cf7f48
Create Date: 2026-08-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4e92a7d3c61'
down_revision = '8fb3a4cf7f48'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('trials', sa.Column('recalled_performance_category', sa.String(length=32), nullable=True))
    op.add_column('participants', sa.Column('demographic_age_range', sa.String(length=32), nullable=True))
    op.add_column('participants', sa.Column('demographic_gender', sa.String(length=64), nullable=True))
    op.add_column('participants', sa.Column('demographic_work_status', sa.String(length=64), nullable=True))
    op.add_column('participants', sa.Column('demographic_work_field', sa.String(length=128), nullable=True))
    op.add_column('participants', sa.Column('demographic_work_experience', sa.String(length=32), nullable=True))
    op.add_column('participants', sa.Column('demographic_nationality', sa.String(length=128), nullable=True))


def downgrade():
    op.drop_column('participants', 'demographic_nationality')
    op.drop_column('participants', 'demographic_work_experience')
    op.drop_column('participants', 'demographic_work_field')
    op.drop_column('participants', 'demographic_work_status')
    op.drop_column('participants', 'demographic_gender')
    op.drop_column('participants', 'demographic_age_range')
    op.drop_column('trials', 'recalled_performance_category')