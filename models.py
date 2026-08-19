import uuid
from datetime import datetime, timezone

from extensions import db


class Participant(db.Model):
    __tablename__ = 'participants'
    __table_args__ = (
        db.UniqueConstraint('prolific_pid', 'prolific_study_id', name='uq_participant_prolific_study'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    recruitment_source = db.Column(db.String(30), nullable=False, default='direct')
    prolific_pid = db.Column(db.String(64), nullable=True, index=True)
    prolific_study_id = db.Column(db.String(64), nullable=True, index=True)
    prolific_session_id = db.Column(db.String(64), nullable=True, index=True)
    consent_given = db.Column(db.Boolean, nullable=False, default=False)
    consent_at = db.Column(db.DateTime, nullable=True)
    study_version = db.Column(db.String(32), nullable=False, default='1.0.0')
    experimental_condition = db.Column(db.String(20), nullable=False, default='ai_assisted')
    profile_order = db.Column(db.JSON, nullable=True)
    attention_check_plan = db.Column(db.JSON, nullable=True)
    current_trial_index = db.Column(db.Integer, nullable=False, default=0)
    resume_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='started')
    completed_at = db.Column(db.DateTime, nullable=True)
    demand_awareness = db.Column(db.Text, nullable=True)
    rating_change_reason = db.Column(db.Text, nullable=True)
    ai_usefulness_1 = db.Column(db.Integer, nullable=True)
    ai_usefulness_2 = db.Column(db.Integer, nullable=True)
    ai_usefulness_3 = db.Column(db.Integer, nullable=True)
    demographic_age_range = db.Column(db.String(32), nullable=True)
    demographic_gender = db.Column(db.String(64), nullable=True)
    demographic_work_status = db.Column(db.String(64), nullable=True)
    demographic_work_field = db.Column(db.String(128), nullable=True)
    demographic_work_experience = db.Column(db.String(32), nullable=True)
    demographic_nationality = db.Column(db.String(128), nullable=True)

    trials = db.relationship('Trial', backref='participant', lazy=True, cascade='all, delete-orphan')
    initial_evaluations = db.relationship('InitialEvaluation', backref='participant', lazy=True, cascade='all, delete-orphan')
    ai_conversations = db.relationship('AIConversation', backref='participant', lazy=True, cascade='all, delete-orphan')


class InitialEvaluation(db.Model):
    __tablename__ = 'initial_evaluations'
    __table_args__ = (
        db.UniqueConstraint('participant_id', 'profile_id', name='uq_initial_evaluation_participant_profile'),
        db.UniqueConstraint('participant_id', 'submission_id', name='uq_initial_evaluation_submission'),
    )

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(36), db.ForeignKey('participants.id'), nullable=False)
    profile_id = db.Column(db.String(50), nullable=False)
    domain = db.Column(db.String(50), nullable=False)
    trial_order = db.Column(db.Integer, nullable=False)
    submission_id = db.Column(db.String(64), nullable=False)
    saved_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    reaction_time_ms = db.Column(db.Integer, nullable=False)

    lead_1 = db.Column(db.Integer, nullable=False)
    lead_2 = db.Column(db.Integer, nullable=False)
    lead_3 = db.Column(db.Integer, nullable=False)
    lead_4 = db.Column(db.Integer, nullable=False)
    prom_1 = db.Column(db.Integer, nullable=False)
    prom_2 = db.Column(db.Integer, nullable=False)
    prom_3 = db.Column(db.Integer, nullable=False)
    bonus_allocation = db.Column(db.Integer, nullable=False)
    attention_check = db.Column(db.Integer, nullable=False)
    attention_check_expected = db.Column(db.Integer, nullable=True)


class Trial(db.Model):
    __tablename__ = 'trials'
    __table_args__ = (
        db.UniqueConstraint('participant_id', 'profile_id', name='uq_trial_participant_profile'),
        db.UniqueConstraint('participant_id', 'submission_id', name='uq_trial_participant_submission'),
    )

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(36), db.ForeignKey('participants.id'), nullable=False)
    profile_id = db.Column(db.String(50), nullable=False)
    domain = db.Column(db.String(50), nullable=False)
    trial_order = db.Column(db.Integer, nullable=False)
    submission_id = db.Column(db.String(64), nullable=True)

    lead_1_pre = db.Column(db.Integer, nullable=False)
    lead_2_pre = db.Column(db.Integer, nullable=False)
    lead_3_pre = db.Column(db.Integer, nullable=False)
    lead_4_pre = db.Column(db.Integer, nullable=False)
    prom_1_pre = db.Column(db.Integer, nullable=False)
    prom_2_pre = db.Column(db.Integer, nullable=False)
    prom_3_pre = db.Column(db.Integer, nullable=False)
    bonus_allocation_pre = db.Column(db.Integer, nullable=False)
    attention_check_pre = db.Column(db.Integer, nullable=True)
    attention_check_pre_expected = db.Column(db.Integer, nullable=True)

    lead_1_post = db.Column(db.Integer, nullable=False)
    lead_2_post = db.Column(db.Integer, nullable=False)
    lead_3_post = db.Column(db.Integer, nullable=False)
    lead_4_post = db.Column(db.Integer, nullable=False)
    prom_1_post = db.Column(db.Integer, nullable=False)
    prom_2_post = db.Column(db.Integer, nullable=False)
    prom_3_post = db.Column(db.Integer, nullable=False)
    bonus_allocation_post = db.Column(db.Integer, nullable=False)
    attention_check_post = db.Column(db.Integer, nullable=True)
    attention_check_post_expected = db.Column(db.Integer, nullable=True)

    justification_text = db.Column(db.Text, nullable=True)
    ai_conversation = db.Column(db.Text, nullable=True)
    recalled_performance_score = db.Column(db.Integer, nullable=True)
    recalled_performance_category = db.Column(db.String(32), nullable=True)
    performance_recall_error = db.Column(db.Integer, nullable=True)
    reaction_time_ms = db.Column(db.Integer, nullable=False)
    post_reaction_time_ms = db.Column(db.Integer, nullable=True)


class AIConversation(db.Model):
    __tablename__ = 'ai_conversations'
    __table_args__ = (
        db.UniqueConstraint('participant_id', 'profile_id', name='uq_ai_conversation_participant_profile'),
    )

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(36), db.ForeignKey('participants.id'), nullable=False)
    profile_id = db.Column(db.String(50), nullable=False)
    request_count = db.Column(db.Integer, nullable=False, default=0)
    messages = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
