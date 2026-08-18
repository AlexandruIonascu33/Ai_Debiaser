"""create experiment data schema

Revision ID: 8fb3a4cf7f48
Revises: 
Create Date: 2026-08-06 14:05:08.392822

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8fb3a4cf7f48'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'participants',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('recruitment_source', sa.String(length=30), nullable=False),
        sa.Column('prolific_pid', sa.String(length=64), nullable=True),
        sa.Column('prolific_study_id', sa.String(length=64), nullable=True),
        sa.Column('prolific_session_id', sa.String(length=64), nullable=True),
        sa.Column('consent_given', sa.Boolean(), nullable=False),
        sa.Column('consent_at', sa.DateTime(), nullable=True),
        sa.Column('study_version', sa.String(length=32), nullable=False),
        sa.Column('experimental_condition', sa.String(length=20), nullable=False),
        sa.Column('profile_order', sa.JSON(), nullable=True),
        sa.Column('current_trial_index', sa.Integer(), nullable=False),
        sa.Column('resume_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('demand_awareness', sa.Text(), nullable=True),
        sa.Column('rating_change_reason', sa.Text(), nullable=True),
        sa.Column('ai_usefulness_1', sa.Integer(), nullable=True),
        sa.Column('ai_usefulness_2', sa.Integer(), nullable=True),
        sa.Column('ai_usefulness_3', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('prolific_pid', 'prolific_study_id', name='uq_participant_prolific_study'),
    )
    op.create_index('ix_participants_prolific_pid', 'participants', ['prolific_pid'])
    op.create_index('ix_participants_prolific_study_id', 'participants', ['prolific_study_id'])

    op.create_table(
        'initial_evaluations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('participant_id', sa.String(length=36), nullable=False),
        sa.Column('profile_id', sa.String(length=50), nullable=False),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('trial_order', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.String(length=64), nullable=False),
        sa.Column('saved_at', sa.DateTime(), nullable=False),
        sa.Column('reaction_time_ms', sa.Integer(), nullable=False),
        sa.Column('lead_1', sa.Integer(), nullable=False),
        sa.Column('lead_2', sa.Integer(), nullable=False),
        sa.Column('lead_3', sa.Integer(), nullable=False),
        sa.Column('lead_4', sa.Integer(), nullable=False),
        sa.Column('prom_1', sa.Integer(), nullable=False),
        sa.Column('prom_2', sa.Integer(), nullable=False),
        sa.Column('prom_3', sa.Integer(), nullable=False),
        sa.Column('bonus_allocation', sa.Integer(), nullable=False),
        sa.Column('attention_check', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('participant_id', 'profile_id', name='uq_initial_evaluation_participant_profile'),
        sa.UniqueConstraint('participant_id', 'submission_id', name='uq_initial_evaluation_submission'),
    )

    op.create_table(
        'trials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('participant_id', sa.String(length=36), nullable=False),
        sa.Column('profile_id', sa.String(length=50), nullable=False),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('trial_order', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.String(length=64), nullable=True),
        sa.Column('lead_1_pre', sa.Integer(), nullable=False),
        sa.Column('lead_2_pre', sa.Integer(), nullable=False),
        sa.Column('lead_3_pre', sa.Integer(), nullable=False),
        sa.Column('lead_4_pre', sa.Integer(), nullable=False),
        sa.Column('prom_1_pre', sa.Integer(), nullable=False),
        sa.Column('prom_2_pre', sa.Integer(), nullable=False),
        sa.Column('prom_3_pre', sa.Integer(), nullable=False),
        sa.Column('bonus_allocation_pre', sa.Integer(), nullable=False),
        sa.Column('attention_check_pre', sa.Integer(), nullable=True),
        sa.Column('lead_1_post', sa.Integer(), nullable=False),
        sa.Column('lead_2_post', sa.Integer(), nullable=False),
        sa.Column('lead_3_post', sa.Integer(), nullable=False),
        sa.Column('lead_4_post', sa.Integer(), nullable=False),
        sa.Column('prom_1_post', sa.Integer(), nullable=False),
        sa.Column('prom_2_post', sa.Integer(), nullable=False),
        sa.Column('prom_3_post', sa.Integer(), nullable=False),
        sa.Column('bonus_allocation_post', sa.Integer(), nullable=False),
        sa.Column('attention_check_post', sa.Integer(), nullable=True),
        sa.Column('justification_text', sa.Text(), nullable=True),
        sa.Column('ai_conversation', sa.Text(), nullable=True),
        sa.Column('recalled_performance_score', sa.Integer(), nullable=True),
        sa.Column('performance_recall_error', sa.Integer(), nullable=True),
        sa.Column('reaction_time_ms', sa.Integer(), nullable=False),
        sa.Column('post_reaction_time_ms', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('participant_id', 'profile_id', name='uq_trial_participant_profile'),
        sa.UniqueConstraint('participant_id', 'submission_id', name='uq_trial_participant_submission'),
    )


def downgrade():
    op.drop_table('trials')
    op.drop_table('initial_evaluations')
    op.drop_index('ix_participants_prolific_study_id', table_name='participants')
    op.drop_index('ix_participants_prolific_pid', table_name='participants')
    op.drop_table('participants')
