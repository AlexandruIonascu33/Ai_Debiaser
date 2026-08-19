"""add technical difficulties feedback

Revision ID: e1b4c7d9f2a6
Revises: c7a9d2e4f6b8
Create Date: 2026-08-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1b4c7d9f2a6'
down_revision = 'c7a9d2e4f6b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('participants', sa.Column('technical_difficulties', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('participants', 'technical_difficulties')