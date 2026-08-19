"""add AI conversation limits and attention-check plans

Revision ID: c7a9d2e4f6b8
Revises: b4e92a7d3c61
Create Date: 2026-08-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c7a9d2e4f6b8'
down_revision = 'b4e92a7d3c61'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('participants', sa.Column('attention_check_plan', sa.JSON(), nullable=True))
    op.add_column('initial_evaluations', sa.Column('attention_check_expected', sa.Integer(), nullable=True))
    op.add_column('trials', sa.Column('attention_check_pre_expected', sa.Integer(), nullable=True))
    op.add_column('trials', sa.Column('attention_check_post_expected', sa.Integer(), nullable=True))
    op.create_table(
        'ai_conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('participant_id', sa.String(length=36), nullable=False),
        sa.Column('profile_id', sa.String(length=50), nullable=False),
        sa.Column('request_count', sa.Integer(), nullable=False),
        sa.Column('messages', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('participant_id', 'profile_id', name='uq_ai_conversation_participant_profile'),
    )


def downgrade():
    op.drop_table('ai_conversations')
    op.drop_column('trials', 'attention_check_post_expected')
    op.drop_column('trials', 'attention_check_pre_expected')
    op.drop_column('initial_evaluations', 'attention_check_expected')
    op.drop_column('participants', 'attention_check_plan')