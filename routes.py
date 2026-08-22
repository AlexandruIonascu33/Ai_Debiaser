import csv
import hmac
import io
import json
import logging
import os
import secrets
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session
from sqlalchemy import select

from extensions import db, limiter
from models import AIConversation, InitialEvaluation, Participant, Trial
from utils import (
    admin_required,
    get_active_participant,
    get_admin_key,
    get_attention_check_expected,
    get_completion_url,
    get_prolific_metadata,
    is_valid_bonus_allocation,
    is_valid_likert,
    is_valid_reaction_time,
    has_reflection_message,
    PROFILE_DOMAINS,
    PROFILE_PERFORMANCE_SCORES,
    request_ai_reflection,
)

main = Blueprint('main', __name__)
logger = logging.getLogger(__name__)


AI_ASSISTED_CONDITION = 'ai_assisted'
CONTROL_CONDITION = 'control'
EXPERIMENTAL_CONDITIONS = (AI_ASSISTED_CONDITION, CONTROL_CONDITION)
MAX_TEXT_LENGTH = 10_000
MAX_AI_CONTEXT_LENGTH = 4_000
MAX_AI_JUSTIFICATION_LENGTH = 3_000
MAX_AI_MESSAGE_LENGTH = 500
MAX_AI_REQUESTS_PER_PROFILE = 5
MAX_SUBMISSION_ID_LENGTH = 64
PERFORMANCE_RECALL_CATEGORIES = {
    'low_performance',
    'average_performance',
    'high_performance',
    'do_not_remember',
}
DEMOGRAPHIC_OPTIONS = {
    'demographic_gender': {
        'woman', 'man', 'non_binary', 'self_describe', 'prefer_not_to_say',
    },
    'demographic_work_status': {
        'employed_full_time', 'employed_part_time', 'self_employed', 'student',
        'unemployed', 'retired', 'other', 'prefer_not_to_say',
    },
    'demographic_work_field': {
        'technology', 'sales_marketing', 'human_resources', 'finance', 'healthcare',
        'education', 'public_sector', 'engineering_manufacturing', 'customer_service',
        'other', 'prefer_not_to_say',
    },
    'demographic_leadership_position': {
        'yes', 'no', 'prefer_not_to_say',
    },
}


def has_valid_profile_order(profile_order):
    return (
        isinstance(profile_order, list)
        and len(profile_order) == len(PROFILE_PERFORMANCE_SCORES)
        and set(profile_order) == set(PROFILE_PERFORMANCE_SCORES)
    )


def get_study_stage(participant):
    profile_order = participant.profile_order or []
    if participant.current_trial_index < len(profile_order):
        profile_id = profile_order[participant.current_trial_index]
        if InitialEvaluation.query.filter_by(participant_id=participant.id, profile_id=profile_id).first():
            return 'post_evaluation'
        return 'evaluation'
    if Trial.query.filter_by(participant_id=participant.id, recalled_performance_score=None).count():
        return 'final_recall'
    return 'final_questionnaire'


def get_json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def get_text_value(data, field_name, minimum_length=0, maximum_length=MAX_TEXT_LENGTH):
    value = data.get(field_name)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not minimum_length <= len(value) <= maximum_length:
        return None
    return value


def get_bounded_integer(data, field_name, minimum_value, maximum_value):
    value = data.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not minimum_value <= value <= maximum_value:
        return None
    return value


def get_demographic_responses(data):
    responses = {}
    for field_name, accepted_values in DEMOGRAPHIC_OPTIONS.items():
        value = data.get(field_name)
        if value not in accepted_values:
            return None
        responses[field_name] = value

    age = get_bounded_integer(data, 'demographic_age', minimum_value=18, maximum_value=120)
    years_experience = get_bounded_integer(data, 'demographic_years_experience', minimum_value=0, maximum_value=100)
    if age is None or years_experience is None:
        return None
    responses['demographic_age'] = age
    responses['demographic_years_experience'] = years_experience

    nationality = get_text_value(data, 'demographic_nationality', minimum_length=1, maximum_length=128)
    if not nationality:
        return None
    responses['demographic_nationality'] = nationality
    return responses


def is_valid_submission_id(value):
    return (
        isinstance(value, str)
        and 8 <= len(value) <= MAX_SUBMISSION_ID_LENGTH
        and all(character.isalnum() or character == '-' for character in value)
    )


def get_locked_participant(data):
    participant = get_active_participant(data)
    if not participant:
        return None
    return db.session.execute(
        select(Participant).where(Participant.id == participant.id).with_for_update()
    ).scalar_one()


def api_server_error(context):
    db.session.rollback()
    logger.exception(context)
    return jsonify({'status': 'error', 'message': 'A server error occurred. Please try again.'}), 500


def serialize_initial_evaluation(initial_evaluation):
    return {
        'lead_1': initial_evaluation.lead_1,
        'lead_2': initial_evaluation.lead_2,
        'lead_3': initial_evaluation.lead_3,
        'lead_4': initial_evaluation.lead_4,
        'prom_1': initial_evaluation.prom_1,
        'prom_2': initial_evaluation.prom_2,
        'prom_3': initial_evaluation.prom_3,
        'bonus_allocation': initial_evaluation.bonus_allocation,
        'attention_check': initial_evaluation.attention_check,
    }


@main.route('/')
def index():
    prolific_metadata = get_prolific_metadata()
    active_participant = db.session.get(Participant, session.get('participant_id'))
    has_active_participant_session = bool(active_participant and active_participant.status != 'completed')

    if any(prolific_metadata.values()) or not has_active_participant_session:
        session['recruitment_metadata'] = prolific_metadata
        session['recruitment_source'] = 'prolific' if any(prolific_metadata.values()) else 'direct'

    if has_active_participant_session:
        session.permanent = True
    return render_template('index.html', has_active_participant_session=has_active_participant_session)


@main.route('/healthz')
def health_check():
    try:
        db.session.execute(select(1))
        return jsonify({'status': 'ok'}), 200
    except Exception:
        logger.exception('Health check failed')
        return jsonify({'status': 'error'}), 503


@main.route('/api/init_session', methods=['POST'])
def init_session():
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400
    try:
        if not data.get('consent_accepted'):
            return jsonify({'status': 'error', 'message': 'Informed consent is required.'}), 400

        profile_order = data.get('profile_order')
        if not has_valid_profile_order(profile_order):
            return jsonify({'status': 'error', 'message': 'The study order must contain each candidate exactly once.'}), 400

        recruitment_metadata = session.get('recruitment_metadata', {})
        recruitment_source = session.get('recruitment_source', 'direct')
        if current_app.config['REQUIRE_PROLIFIC_METADATA'] and not all(recruitment_metadata.values()):
            return jsonify({'status': 'error', 'message': 'This study must be started from its Prolific link.'}), 403
        participant = db.session.get(Participant, session.get('participant_id'))
        if participant and participant.status == 'completed':
            return jsonify({'status': 'error', 'message': 'This study session has already been completed.'}), 409
        if participant and not has_valid_profile_order(participant.profile_order):
            session.pop('participant_id', None)
            participant = None

        if not participant and recruitment_source == 'prolific' and recruitment_metadata.get('prolific_pid') and recruitment_metadata.get('prolific_study_id'):
            participant = Participant.query.filter_by(
                prolific_pid=recruitment_metadata['prolific_pid'],
                prolific_study_id=recruitment_metadata['prolific_study_id']
            ).first()

        if participant and participant.status == 'completed':
            return jsonify({'status': 'error', 'message': 'This Prolific submission has already been completed.'}), 409

        if participant:
            if participant.recruitment_source == 'prolific':
                participant.prolific_session_id = recruitment_metadata.get('prolific_session_id') or participant.prolific_session_id
            participant.status = 'started'
            participant.resume_count += 1
        else:
            participant = Participant(
                recruitment_source=recruitment_source,
                prolific_pid=recruitment_metadata.get('prolific_pid'),
                prolific_study_id=recruitment_metadata.get('prolific_study_id'),
                prolific_session_id=recruitment_metadata.get('prolific_session_id'),
                consent_given=True,
                consent_at=datetime.now(timezone.utc),
                study_version=os.environ.get('STUDY_VERSION', '1.0.0').strip()[:32] or '1.0.0',
                experimental_condition=secrets.choice(EXPERIMENTAL_CONDITIONS),
                profile_order=profile_order,
                status='started'
            )
            db.session.add(participant)

        db.session.commit()
        session.permanent = True
        session['participant_id'] = participant.id
        study_stage = get_study_stage(participant)
        response_data = {
            'status': 'success',
            'participant_id': participant.id,
            'experimental_condition': participant.experimental_condition,
            'profile_order': participant.profile_order,
            'current_trial_index': participant.current_trial_index,
            'study_stage': study_stage,
            'resumed': participant.current_trial_index > 0
        }
        if study_stage == 'post_evaluation':
            profile_id = participant.profile_order[participant.current_trial_index]
            initial_evaluation = InitialEvaluation.query.filter_by(
                participant_id=participant.id, profile_id=profile_id
            ).one()
            response_data['initial_evaluation'] = serialize_initial_evaluation(initial_evaluation)
            conversation = AIConversation.query.filter_by(
                participant_id=participant.id, profile_id=profile_id
            ).first()
            response_data['has_reflection_message'] = has_reflection_message(
                conversation.messages if conversation else None
            )
        return jsonify(response_data), 201
    except Exception:
        return api_server_error('Unable to initialize participant session')


@main.route('/api/save_initial_evaluation', methods=['POST'])
def save_initial_evaluation():
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400

    try:
        participant = get_locked_participant(data)
        if not participant:
            return jsonify({'status': 'error', 'message': 'No active participant session.'}), 401

        profile_order = participant.profile_order or []
        current_index = participant.current_trial_index
        profile_id = data.get('profile_id')
        submission_id = data.get('submission_id')
        if current_index >= len(profile_order) or profile_id != profile_order[current_index]:
            return jsonify({'status': 'error', 'message': 'This is not the active profile.'}), 400
        if not is_valid_submission_id(submission_id):
            return jsonify({'status': 'error', 'message': 'A valid submission identifier is required.'}), 400

        required_likert_fields = ['lead_1', 'lead_2', 'lead_3', 'lead_4', 'prom_1', 'prom_2', 'prom_3']
        if not all(is_valid_likert(data.get(field)) for field in required_likert_fields):
            return jsonify({'status': 'error', 'message': 'All Likert responses must be integers from 1 to 7.'}), 400
        if not is_valid_likert(data.get('attention_check')):
            return jsonify({'status': 'error', 'message': 'The instruction-check response is required.'}), 400
        attention_check_expected = get_attention_check_expected(profile_order, profile_id, 'pre')
        if not attention_check_expected:
            return jsonify({'status': 'error', 'message': 'The instruction-check configuration is unavailable.'}), 500
        if not is_valid_bonus_allocation(data.get('bonus_allocation')):
            return jsonify({'status': 'error', 'message': 'The bonus allocation must be a valid amount between $0 and $3,000.'}), 400
        if not is_valid_reaction_time(data.get('reaction_time_ms')):
            return jsonify({'status': 'error', 'message': 'A valid reaction time is required.'}), 400

        existing_evaluation = InitialEvaluation.query.filter_by(
            participant_id=participant.id, profile_id=profile_id
        ).first()
        if existing_evaluation:
            if existing_evaluation.submission_id == submission_id:
                return jsonify({
                    'status': 'success',
                    'study_stage': 'post_evaluation',
                    'initial_evaluation': serialize_initial_evaluation(existing_evaluation),
                }), 200
            return jsonify({'status': 'error', 'message': 'The initial evaluation was already saved.'}), 409

        initial_evaluation = InitialEvaluation(
            participant_id=participant.id,
            profile_id=profile_id,
            domain=PROFILE_DOMAINS[profile_id],
            trial_order=current_index + 1,
            submission_id=submission_id,
            reaction_time_ms=data['reaction_time_ms'],
            lead_1=data['lead_1'], lead_2=data['lead_2'], lead_3=data['lead_3'], lead_4=data['lead_4'],
            prom_1=data['prom_1'], prom_2=data['prom_2'], prom_3=data['prom_3'],
            bonus_allocation=data['bonus_allocation'], attention_check=data['attention_check'],
            attention_check_expected=attention_check_expected,
        )
        db.session.add(initial_evaluation)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'study_stage': 'post_evaluation',
            'initial_evaluation': serialize_initial_evaluation(initial_evaluation),
        }), 201
    except Exception:
        return api_server_error('Unable to save initial evaluation')


@main.route('/api/save_trial', methods=['POST'])
def save_trial():
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400

    try:
        participant = get_locked_participant(data)
        if not participant:
            return jsonify({'status': 'error', 'message': 'No active participant session.'}), 401

        profile_order = participant.profile_order or []
        current_index = participant.current_trial_index
        profile_id = data.get('profile_id')
        submission_id = data.get('submission_id')
        if not isinstance(profile_id, str) or not is_valid_submission_id(submission_id):
            return jsonify({'status': 'error', 'message': 'A valid profile and submission identifier are required.'}), 400

        existing_trial = Trial.query.filter_by(participant_id=participant.id, profile_id=profile_id).first()
        if existing_trial:
            if existing_trial.submission_id == submission_id:
                return jsonify({'status': 'success', 'is_complete': participant.current_trial_index >= len(profile_order)}), 200
            return jsonify({'status': 'error', 'message': 'The final evaluation was already saved.'}), 409

        if current_index >= len(profile_order) or profile_id != profile_order[current_index]:
            return jsonify({'status': 'error', 'message': 'This is not the active profile.'}), 400

        initial_evaluation = InitialEvaluation.query.filter_by(
            participant_id=participant.id, profile_id=profile_id
        ).first()
        if not initial_evaluation:
            return jsonify({'status': 'error', 'message': 'The initial evaluation must be saved before the final evaluation.'}), 409

        required_likert_fields = ['lead_1_post', 'lead_2_post', 'lead_3_post', 'lead_4_post', 'prom_1_post', 'prom_2_post', 'prom_3_post']
        if not all(is_valid_likert(data.get(field)) for field in required_likert_fields):
            return jsonify({'status': 'error', 'message': 'All Likert responses must be integers from 1 to 7.'}), 400
        if not is_valid_likert(data.get('attention_check_post')):
            return jsonify({'status': 'error', 'message': 'The instruction-check response is required.'}), 400
        attention_check_post_expected = get_attention_check_expected(profile_order, profile_id, 'post')
        if not attention_check_post_expected:
            return jsonify({'status': 'error', 'message': 'The instruction-check configuration is unavailable.'}), 500
        if not is_valid_bonus_allocation(data.get('bonus_allocation_post')):
            return jsonify({'status': 'error', 'message': 'The bonus allocation must be a valid amount between $0 and $3,000.'}), 400
        post_reaction_time_ms = data.get('post_reaction_time_ms')
        if not is_valid_reaction_time(post_reaction_time_ms):
            return jsonify({'status': 'error', 'message': 'A valid reaction time is required.'}), 400
        justification_text = get_text_value(data, 'justification_text', minimum_length=50)
        if not justification_text:
            return jsonify({'status': 'error', 'message': 'Please explain your reasoning in a few words before continuing.'}), 400

        is_ai_assisted = participant.experimental_condition == AI_ASSISTED_CONDITION
        ai_conversation = None
        if is_ai_assisted:
            conversation = AIConversation.query.filter_by(
                participant_id=participant.id, profile_id=profile_id
            ).first()
            if not conversation or not has_reflection_message(conversation.messages):
                return jsonify({'status': 'error', 'message': 'Please send the AI assistant a short response before continuing.'}), 400
            ai_conversation = json.dumps(conversation.messages, ensure_ascii=True)

        trial = Trial(
            participant_id=participant.id,
            profile_id=profile_id,
            domain=initial_evaluation.domain,
            trial_order=initial_evaluation.trial_order,
            submission_id=submission_id,
            lead_1_pre=initial_evaluation.lead_1, lead_2_pre=initial_evaluation.lead_2,
            lead_3_pre=initial_evaluation.lead_3, lead_4_pre=initial_evaluation.lead_4,
            prom_1_pre=initial_evaluation.prom_1, prom_2_pre=initial_evaluation.prom_2,
            prom_3_pre=initial_evaluation.prom_3, bonus_allocation_pre=initial_evaluation.bonus_allocation,
            attention_check_pre=initial_evaluation.attention_check,
            lead_1_post=data['lead_1_post'], lead_2_post=data['lead_2_post'],
            lead_3_post=data['lead_3_post'], lead_4_post=data['lead_4_post'],
            prom_1_post=data['prom_1_post'], prom_2_post=data['prom_2_post'],
            prom_3_post=data['prom_3_post'], bonus_allocation_post=data['bonus_allocation_post'],
            attention_check_post=data['attention_check_post'],
            attention_check_pre_expected=initial_evaluation.attention_check_expected,
            attention_check_post_expected=attention_check_post_expected,
            justification_text=justification_text,
            ai_conversation=ai_conversation,
            reaction_time_ms=initial_evaluation.reaction_time_ms + post_reaction_time_ms,
            post_reaction_time_ms=post_reaction_time_ms,
        )
        db.session.add(trial)
        participant.current_trial_index = current_index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'is_complete': participant.current_trial_index >= len(profile_order)}), 201
    except Exception:
        return api_server_error('Unable to save final evaluation')


@main.route('/api/save_final_recall', methods=['POST'])
def save_final_recall():
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400
    try:
        participant = get_locked_participant(data)
        if not participant:
            return jsonify({'status': 'error', 'message': 'No active participant session.'}), 401

        trials = Trial.query.filter_by(participant_id=participant.id).order_by(Trial.trial_order).all()
        if len(trials) != len(participant.profile_order or []):
            return jsonify({'status': 'error', 'message': 'All candidate evaluations must be saved first.'}), 400

        recalled_scores = data.get('recalled_performance_scores')
        recalled_categories = data.get('recalled_performance_categories')
        expected_profile_ids = {trial.profile_id for trial in trials}
        if not isinstance(recalled_scores, dict) or set(recalled_scores) != expected_profile_ids:
            return jsonify({'status': 'error', 'message': 'Please provide one performance score for every candidate.'}), 400
        if not isinstance(recalled_categories, dict) or set(recalled_categories) != expected_profile_ids:
            return jsonify({'status': 'error', 'message': 'Please provide one performance category for every candidate.'}), 400
        for trial in trials:
            recalled_score = recalled_scores.get(trial.profile_id)
            if type(recalled_score) is not int or not 0 <= recalled_score <= 100:
                return jsonify({'status': 'error', 'message': 'Please provide a valid performance score for every candidate.'}), 400
            recalled_category = recalled_categories.get(trial.profile_id)
            if recalled_category not in PERFORMANCE_RECALL_CATEGORIES:
                return jsonify({'status': 'error', 'message': 'Please provide a valid performance category for every candidate.'}), 400
            trial.recalled_performance_score = recalled_score
            trial.recalled_performance_category = recalled_category
            trial.performance_recall_error = PROFILE_PERFORMANCE_SCORES[trial.profile_id] - recalled_score

        db.session.commit()
        return jsonify({'status': 'success'}), 200
    except Exception:
        return api_server_error('Unable to save final recall')


@main.route('/api/ai_chat', methods=['POST'])
@limiter.limit(lambda: current_app.config['AI_CHAT_RATE_LIMIT'])
def ai_chat():
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400
    try:
        participant = get_locked_participant(data)
        profile_id = data.get('profile_id')
        evaluation_context = data.get('evaluation_context')
        if not participant:
            return jsonify({'status': 'error', 'message': 'No active participant session.'}), 401
        if participant.experimental_condition != AI_ASSISTED_CONDITION:
            return jsonify({'status': 'error', 'message': 'AI reflection is not available for this study condition.'}), 403
        if not os.environ.get('OPENAI_API_KEY'):
            return jsonify({'status': 'error', 'message': 'The OpenAI API key is not configured.'}), 500
        if not isinstance(profile_id, str) or not isinstance(evaluation_context, dict) or evaluation_context.get('profile_id') != profile_id:
            return jsonify({'status': 'error', 'message': 'A valid profile-specific AI reflection request is required.'}), 400
        if len(json.dumps(evaluation_context, ensure_ascii=True)) > MAX_AI_CONTEXT_LENGTH:
            return jsonify({'status': 'error', 'message': 'The AI reflection context is too large.'}), 400
        profile_order = participant.profile_order or []
        if participant.current_trial_index >= len(profile_order) or profile_id != profile_order[participant.current_trial_index]:
            return jsonify({'status': 'error', 'message': 'The AI context does not match the active profile.'}), 400
        if not InitialEvaluation.query.filter_by(participant_id=participant.id, profile_id=profile_id).first():
            return jsonify({'status': 'error', 'message': 'Save the initial evaluation before starting the AI reflection.'}), 409

        conversation = AIConversation.query.filter_by(
            participant_id=participant.id, profile_id=profile_id
        ).with_for_update().first()
        messages = conversation.messages if conversation else []
        if conversation and conversation.request_count >= MAX_AI_REQUESTS_PER_PROFILE:
            return jsonify({'status': 'error', 'message': 'The AI reflection limit for this candidate has been reached.'}), 429

        if not messages:
            justification = get_text_value(data, 'justification', maximum_length=MAX_AI_JUSTIFICATION_LENGTH)
            if not justification:
                return jsonify({'status': 'error', 'message': 'Write a justification for the AI assistant before starting the reflection.'}), 400
            conversation = AIConversation(
                participant_id=participant.id,
                profile_id=profile_id,
                request_count=0,
                messages=[],
            )
            db.session.add(conversation)
            messages = [{'role': 'user', 'content': justification}]
        else:
            message = get_text_value(data, 'message', maximum_length=MAX_AI_MESSAGE_LENGTH)
            if message is None or not message:
                return jsonify({'status': 'error', 'message': 'Write a message for the AI assistant before sending it.'}), 400
            messages = [*messages, {'role': 'user', 'content': message}]

        response = request_ai_reflection(evaluation_context, messages, messages[0]['content'])
        conversation.messages = [*messages, {'role': 'assistant', 'content': response}]
        conversation.request_count += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'conversation': conversation.messages,
            'remaining_responses': MAX_AI_REQUESTS_PER_PROFILE - conversation.request_count,
        })
    except Exception:
        db.session.rollback()
        logger.exception('AI reflection request failed')
        return jsonify({'status': 'error', 'message': 'The AI assistant is temporarily unavailable. Please try again.'}), 502


@main.route('/api/finish_session', methods=['POST'])
def finish_session():
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400
    try:
        participant = get_locked_participant(data)
        if not participant:
            return jsonify({'status': 'not_found'}), 404
        if Trial.query.filter_by(participant_id=participant.id).count() != len(participant.profile_order or []):
            return jsonify({'status': 'error', 'message': 'All profiles must be completed before finishing.'}), 400
        if Trial.query.filter_by(participant_id=participant.id, recalled_performance_score=None).count():
            return jsonify({'status': 'error', 'message': 'Final performance recall must be completed first.'}), 400

        demand_awareness = get_text_value(data, 'demand_awareness', minimum_length=1)
        rating_change_reason = get_text_value(data, 'rating_change_reason', minimum_length=1)
        technical_difficulties = get_text_value(data, 'technical_difficulties', minimum_length=1, maximum_length=2_000)
        demographic_responses = get_demographic_responses(data)
        is_ai_assisted = participant.experimental_condition == AI_ASSISTED_CONDITION
        ai_usefulness = [data.get(f'ai_usefulness_{index}') for index in range(1, 4)]
        if not demand_awareness:
            return jsonify({'status': 'error', 'message': 'The final study-purpose question is required.'}), 400
        if not rating_change_reason:
            return jsonify({'status': 'error', 'message': 'A response about changes to evaluations is required.'}), 400
        if not technical_difficulties:
            return jsonify({'status': 'error', 'message': 'Please describe any technical difficulties, or enter None.'}), 400
        if not demographic_responses:
            return jsonify({'status': 'error', 'message': 'Please complete all demographic questions or select prefer not to say.'}), 400
        if is_ai_assisted and not all(is_valid_likert(response) for response in ai_usefulness):
            return jsonify({'status': 'error', 'message': 'All AI usefulness questions must be answered.'}), 400

        participant.demand_awareness = demand_awareness
        participant.rating_change_reason = rating_change_reason
        participant.technical_difficulties = technical_difficulties
        participant.demographic_age = demographic_responses['demographic_age']
        participant.demographic_gender = demographic_responses['demographic_gender']
        participant.demographic_work_status = demographic_responses['demographic_work_status']
        participant.demographic_work_field = demographic_responses['demographic_work_field']
        participant.demographic_years_experience = demographic_responses['demographic_years_experience']
        participant.demographic_leadership_position = demographic_responses['demographic_leadership_position']
        participant.demographic_nationality = demographic_responses['demographic_nationality']
        if is_ai_assisted:
            participant.ai_usefulness_1, participant.ai_usefulness_2, participant.ai_usefulness_3 = ai_usefulness
        participant.status = 'completed'
        participant.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({'status': 'success', 'completion_url': get_completion_url(participant)}), 200
    except Exception:
        return api_server_error('Unable to complete participant session')


@main.route('/admin_panel')
def admin_panel():
    if not session.get('is_admin'):
        return render_template('admin_login.html')
    trials = Trial.query.order_by(Trial.id.desc()).limit(100).all()
    return render_template('admin.html', trials=trials)


@main.route('/api/admin/login', methods=['POST'])
def admin_login():
    expected_key = get_admin_key()
    data = get_json_object()
    if data is None:
        return jsonify({'status': 'error', 'message': 'A JSON object is required.'}), 400
    supplied_key = data.get('admin_key', '')
    if not expected_key:
        return jsonify({'status': 'error', 'message': 'Admin access is not configured.'}), 503
    if not isinstance(supplied_key, str) or not hmac.compare_digest(supplied_key, expected_key):
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    session.clear()
    session.permanent = True
    session['is_admin'] = True
    return jsonify({'status': 'success'})


@main.route('/api/admin/logout', methods=['POST'])
@admin_required
def admin_logout():
    session.clear()
    return redirect('/admin_panel')


def csv_safe_value(value):
    if isinstance(value, str) and value and value[0] in {'=', '+', '-', '@', '\t', '\r'}:
        return f"'{value}"
    return value


def write_csv_row(writer, values):
    writer.writerow([csv_safe_value(value) for value in values])


@main.route('/export_csv')
@admin_required
def export_csv():
    query = db.session.query(Trial, Participant).join(Participant, Trial.participant_id == Participant.id).order_by(
        Participant.created_at.asc(), Trial.trial_order.asc(), Trial.id.asc()
    ).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    write_csv_row(writer, [
        'trial_db_id', 'participant_id', 'recruitment_source', 'prolific_pid',
        'prolific_study_id', 'prolific_session_id', 'consent_given', 'consent_at',
        'participant_status', 'study_version', 'resume_count', 'experimental_condition', 'session_start', 'completed_at', 'demand_awareness', 'rating_change_reason', 'technical_difficulties',
        'ai_usefulness_1', 'ai_usefulness_2', 'ai_usefulness_3',
        'demographic_age_range', 'demographic_age', 'demographic_gender', 'demographic_work_status', 'demographic_work_field',
        'demographic_work_experience', 'demographic_years_experience', 'demographic_leadership_position', 'demographic_nationality',
        'trial_order', 'profile_id', 'domain',
        'lead_1_pre', 'lead_2_pre', 'lead_3_pre', 'lead_4_pre',
        'prom_1_pre', 'prom_2_pre', 'prom_3_pre', 'bonus_allocation_pre',
        'attention_check_pre', 'attention_check_pre_expected', 'attention_check_pre_correct',
        'lead_1_post', 'lead_2_post', 'lead_3_post', 'lead_4_post',
        'prom_1_post', 'prom_2_post', 'prom_3_post', 'bonus_allocation_post',
        'attention_check_post', 'attention_check_post_expected', 'attention_check_post_correct',
        'justification_text', 'ai_conversation', 'recalled_performance_score', 'recalled_performance_category',
        'performance_recall_error', 'reaction_time_ms'
    ])
    for trial, participant in query:
        write_csv_row(writer, [
            trial.id, participant.id, participant.recruitment_source, participant.prolific_pid,
            participant.prolific_study_id, participant.prolific_session_id, participant.consent_given,
            participant.consent_at, participant.status, participant.study_version, participant.resume_count, participant.experimental_condition, participant.created_at, participant.completed_at,
            participant.demand_awareness, participant.rating_change_reason, participant.technical_difficulties, participant.ai_usefulness_1, participant.ai_usefulness_2,
            participant.ai_usefulness_3, participant.demographic_age_range, participant.demographic_age,
            participant.demographic_gender, participant.demographic_work_status, participant.demographic_work_field,
            participant.demographic_work_experience, participant.demographic_years_experience,
            participant.demographic_leadership_position, participant.demographic_nationality, trial.trial_order,
            trial.profile_id, trial.domain,
            trial.lead_1_pre, trial.lead_2_pre, trial.lead_3_pre, trial.lead_4_pre,
            trial.prom_1_pre, trial.prom_2_pre, trial.prom_3_pre, trial.bonus_allocation_pre,
            trial.attention_check_pre, trial.attention_check_pre_expected,
            trial.attention_check_pre == trial.attention_check_pre_expected,
            trial.lead_1_post, trial.lead_2_post, trial.lead_3_post, trial.lead_4_post,
            trial.prom_1_post, trial.prom_2_post, trial.prom_3_post, trial.bonus_allocation_post,
            trial.attention_check_post, trial.attention_check_post_expected,
            trial.attention_check_post == trial.attention_check_post_expected,
            trial.justification_text, trial.ai_conversation, trial.recalled_performance_score, trial.recalled_performance_category,
            trial.performance_recall_error,
            trial.reaction_time_ms
        ])
    return Response(
        '\ufeff' + stream.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=final_experiment_export.csv'}
    )


@main.route('/export_initial_evaluations_csv')
@admin_required
def export_initial_evaluations_csv():
    query = db.session.query(InitialEvaluation, Participant, Trial).join(
        Participant, InitialEvaluation.participant_id == Participant.id
    ).outerjoin(
        Trial,
        (Trial.participant_id == InitialEvaluation.participant_id)
        & (Trial.profile_id == InitialEvaluation.profile_id)
    ).order_by(Participant.created_at.asc(), InitialEvaluation.trial_order.asc()).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    write_csv_row(writer, [
        'initial_evaluation_id', 'participant_id', 'prolific_pid', 'prolific_study_id',
        'participant_status', 'study_version', 'resume_count', 'experimental_condition', 'session_start',
        'trial_order', 'profile_id', 'domain', 'initial_submission_id', 'initial_saved_at',
        'lead_1_pre', 'lead_2_pre', 'lead_3_pre', 'lead_4_pre', 'prom_1_pre', 'prom_2_pre', 'prom_3_pre',
        'bonus_allocation_pre', 'attention_check_pre', 'attention_check_pre_expected', 'attention_check_pre_correct', 'initial_reaction_time_ms',
        'final_evaluation_saved', 'final_submission_id',
    ])
    for initial_evaluation, participant, trial in query:
        write_csv_row(writer, [
            initial_evaluation.id, participant.id, participant.prolific_pid, participant.prolific_study_id,
            participant.status, participant.study_version, participant.resume_count, participant.experimental_condition, participant.created_at,
            initial_evaluation.trial_order, initial_evaluation.profile_id, initial_evaluation.domain,
            initial_evaluation.submission_id, initial_evaluation.saved_at,
            initial_evaluation.lead_1, initial_evaluation.lead_2, initial_evaluation.lead_3, initial_evaluation.lead_4,
            initial_evaluation.prom_1, initial_evaluation.prom_2, initial_evaluation.prom_3,
            initial_evaluation.bonus_allocation, initial_evaluation.attention_check,
            initial_evaluation.attention_check_expected,
            initial_evaluation.attention_check == initial_evaluation.attention_check_expected,
            initial_evaluation.reaction_time_ms,
            trial is not None, trial.submission_id if trial else None,
        ])
    return Response(
        '\ufeff' + stream.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=initial_evaluations_export.csv'}
    )
