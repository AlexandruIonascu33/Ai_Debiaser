"""add numeric demographics and leadership position

Revision ID: f2c6e8a1b9d3
Revises: e1b4c7d9f2a6
Create Date: 2026-08-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2c6e8a1b9d3'
down_revision = 'e1b4c7d9f2a6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('participants', sa.Column('demographic_age', sa.Integer(), nullable=True))
    op.add_column('participants', sa.Column('demographic_years_experience', sa.Integer(), nullable=True))
    op.add_column('participants', sa.Column('demographic_leadership_position', sa.String(length=32), nullable=True))


def downgrade():
    op.drop_column('participants', 'demographic_leadership_position')
    op.drop_column('participants', 'demographic_years_experience')
    op.drop_column('participants', 'demographic_age')