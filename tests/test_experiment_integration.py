import csv
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app
from extensions import db
from models import AIConversation, InitialEvaluation, Participant, Trial
from utils import get_completion_url


PROFILE_ORDER = ['it_2', 'it_3', 'sales_2', 'sales_5']
PROFILE_SCORES = {'it_2': 97, 'it_3': 26, 'sales_2': 93, 'sales_5': 31}
PROFILE_CATEGORIES = {
    'it_2': 'high_performance',
    'it_3': 'low_performance',
    'sales_2': 'high_performance',
    'sales_5': 'low_performance',
}
FINAL_DEMOGRAPHICS = {
    'demographic_age': 30,
    'demographic_gender': 'prefer_not_to_say',
    'demographic_work_status': 'employed_full_time',
    'demographic_work_field': 'technology',
    'demographic_years_experience': 6,
    'demographic_leadership_position': 'no',
    'demographic_nationality': 'Romanian',
    'technical_difficulties': 'None',
}


class ExperimentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'SECRET_KEY': 'test-secret-key'})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def start_prolific_session(self, profile_order=PROFILE_ORDER):
        self.client.get('/?PROLIFIC_PID=participant-1&STUDY_ID=study-1&SESSION_ID=session-1')
        response = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': profile_order,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        with self.app.app_context():
            participant = db.session.get(Participant, data['participant_id'])
            participant.experimental_condition = 'control'
            db.session.commit()
        return data

    @staticmethod
    def valid_initial_payload(participant_id, profile_id, trial_order):
        payload = {
            'participant_id': participant_id,
            'profile_id': profile_id,
            'submission_id': f"initial-{trial_order}-{profile_id.replace('_', '-')}",
            'reaction_time_ms': 1200,
            'bonus_allocation': 500,
            'attention_check': (2, 1, 4, 5)[trial_order - 1],
        }
        for field in ('lead_1', 'lead_2', 'lead_3', 'lead_4', 'prom_1', 'prom_2', 'prom_3'):
            payload[field] = 4
        return payload

    @staticmethod
    def valid_final_payload(participant_id, profile_id, trial_order):
        payload = {
            'participant_id': participant_id,
            'profile_id': profile_id,
            'submission_id': f"final-{trial_order}-{profile_id.replace('_', '-')}",
            'post_reaction_time_ms': 800,
            'justification_text': 'The available evidence supports this considered evaluation of the candidate.',
            'bonus_allocation_post': 1000,
            'attention_check_post': (6, 3, 5, 1)[trial_order - 1],
        }
        for field in ('lead_1', 'lead_2', 'lead_3', 'lead_4', 'prom_1', 'prom_2', 'prom_3'):
            payload[f'{field}_post'] = 5
        return payload

    def save_all_trials(self, participant_id, client=None):
        client = client or self.client
        for trial_order, profile_id in enumerate(PROFILE_ORDER, start=1):
            initial_response = client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
                participant_id, profile_id, trial_order
            ))
            self.assertEqual(initial_response.status_code, 201, initial_response.get_json())
            final_response = client.post('/api/save_trial', json=self.valid_final_payload(
                participant_id, profile_id, trial_order
            ))
            self.assertEqual(final_response.status_code, 201, final_response.get_json())

    def test_session_rejects_an_order_with_missing_or_duplicate_profiles(self):
        self.client.get('/?PROLIFIC_PID=participant-1&STUDY_ID=study-1&SESSION_ID=session-1')
        response = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': ['it_2', 'it_2', 'sales_2', 'sales_5'],
        })

        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(Participant.query.count(), 0)

    def test_new_participants_receive_and_persist_a_random_condition(self):
        assigned_conditions = {}
        for index, expected_condition in enumerate(('ai_assisted', 'control'), start=1):
            client = self.app.test_client()
            prolific_pid = f'participant-{index}'
            client.get(f'/?PROLIFIC_PID={prolific_pid}&STUDY_ID=study-1&SESSION_ID=session-{index}')
            with patch('routes.secrets.choice', return_value=expected_condition) as choose_condition:
                response = client.post('/api/init_session', json={
                    'consent_accepted': True,
                    'profile_order': PROFILE_ORDER,
                })
            self.assertEqual(response.status_code, 201, response.get_json())
            self.assertEqual(response.get_json()['experimental_condition'], expected_condition)
            choose_condition.assert_called_once_with(('ai_assisted', 'control'))
            assigned_conditions[prolific_pid] = expected_condition

        with self.app.app_context():
            saved_conditions = {
                participant.prolific_pid: participant.experimental_condition
                for participant in Participant.query.all()
            }
        self.assertEqual(saved_conditions, assigned_conditions)

    def test_trial_data_uses_canonical_domain_and_order_and_rejects_invalid_bonus(self):
        session_data = self.start_prolific_session()
        payload = self.valid_initial_payload(session_data['participant_id'], 'it_2', 1)
        payload['bonus_allocation'] = 525
        invalid_response = self.client.post('/api/save_initial_evaluation', json=payload)
        self.assertEqual(invalid_response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(InitialEvaluation.query.count(), 0)

        payload['bonus_allocation'] = 500
        saved_response = self.client.post('/api/save_initial_evaluation', json=payload)
        self.assertEqual(saved_response.status_code, 201, saved_response.get_json())
        with self.app.app_context():
            initial_evaluation = InitialEvaluation.query.one()
            self.assertEqual(initial_evaluation.domain, 'IT')
            self.assertEqual(initial_evaluation.trial_order, 1)

    def test_attention_check_failures_are_saved_for_manual_review(self):
        session_data = self.start_prolific_session()
        initial_payload = self.valid_initial_payload(session_data['participant_id'], 'it_2', 1)
        initial_payload['attention_check'] = 7
        initial_response = self.client.post('/api/save_initial_evaluation', json=initial_payload)
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())

        final_payload = self.valid_final_payload(session_data['participant_id'], 'it_2', 1)
        final_payload['attention_check_post'] = 2
        final_response = self.client.post('/api/save_trial', json=final_payload)
        self.assertEqual(final_response.status_code, 201, final_response.get_json())
        with self.app.app_context():
            initial_evaluation = InitialEvaluation.query.one()
            trial = Trial.query.one()
            participant = db.session.get(Participant, session_data['participant_id'])
            self.assertEqual(participant.prolific_pid, 'participant-1')
            self.assertEqual(participant.prolific_session_id, 'session-1')
            self.assertEqual((initial_evaluation.attention_check, initial_evaluation.attention_check_expected), (7, 2))
            self.assertEqual((trial.attention_check_post, trial.attention_check_post_expected), (2, 6))

    def test_api_rejects_non_object_json_without_creating_a_participant(self):
        response = self.client.post('/api/init_session', json=['invalid'])
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(Participant.query.count(), 0)

    def test_duplicate_submission_does_not_create_a_second_trial(self):
        session_data = self.start_prolific_session()
        initial_payload = self.valid_initial_payload(session_data['participant_id'], 'it_2', 1)
        initial_response = self.client.post('/api/save_initial_evaluation', json=initial_payload)
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())
        payload = self.valid_final_payload(session_data['participant_id'], 'it_2', 1)

        first_response = self.client.post('/api/save_trial', json=payload)
        duplicate_response = self.client.post('/api/save_trial', json=payload)

        self.assertEqual(first_response.status_code, 201, first_response.get_json())
        self.assertEqual(duplicate_response.status_code, 200, duplicate_response.get_json())
        with self.app.app_context():
            self.assertEqual(Trial.query.count(), 1)

    def test_initial_evaluation_is_persisted_and_resumed_before_final_evaluation(self):
        session_data = self.start_prolific_session()
        initial_payload = self.valid_initial_payload(session_data['participant_id'], 'it_2', 1)
        initial_response = self.client.post('/api/save_initial_evaluation', json=initial_payload)
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())

        resumed_response = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': list(reversed(PROFILE_ORDER)),
        })
        self.assertEqual(resumed_response.status_code, 201, resumed_response.get_json())
        resumed_data = resumed_response.get_json()
        self.assertEqual(resumed_data['study_stage'], 'post_evaluation')
        self.assertEqual(resumed_data['initial_evaluation']['lead_1'], 4)

        final_payload = self.valid_final_payload(session_data['participant_id'], 'it_2', 1)
        final_payload['lead_1_pre'] = 1
        final_response = self.client.post('/api/save_trial', json=final_payload)
        self.assertEqual(final_response.status_code, 201, final_response.get_json())
        with self.app.app_context():
            self.assertEqual(Trial.query.one().lead_1_pre, 4)

    def test_resumed_post_evaluation_reports_saved_ai_reflection(self):
        session_data = self.start_prolific_session()
        initial_response = self.client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
            session_data['participant_id'], 'it_2', 1
        ))
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())
        with self.app.app_context():
            participant = db.session.get(Participant, session_data['participant_id'])
            participant.experimental_condition = 'ai_assisted'
            db.session.add(AIConversation(
                participant_id=participant.id,
                profile_id='it_2',
                request_count=2,
                messages=[
                    {'role': 'user', 'content': 'The performance evidence supports my evaluation.'},
                    {'role': 'assistant', 'content': 'Review the evidence for each rating.'},
                    {'role': 'user', 'content': 'OK'},
                    {'role': 'assistant', 'content': 'You can now reconsider the ratings.'},
                ],
            ))
            db.session.commit()

        resumed_response = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': PROFILE_ORDER,
        })

        self.assertEqual(resumed_response.status_code, 201, resumed_response.get_json())
        self.assertEqual(resumed_response.get_json()['study_stage'], 'post_evaluation')
        self.assertTrue(resumed_response.get_json()['has_reflection_message'])

    def test_prolific_ai_session_can_be_restored_before_sending_a_message(self):
        session_data = self.start_prolific_session()
        with self.app.app_context():
            participant = db.session.get(Participant, session_data['participant_id'])
            participant.experimental_condition = 'ai_assisted'
            db.session.commit()
        initial_response = self.client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
            session_data['participant_id'], 'it_2', 1
        ))
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())

        returning_client = self.app.test_client()
        returning_client.get('/?PROLIFIC_PID=participant-1&STUDY_ID=study-1&SESSION_ID=session-return')
        resume_response = returning_client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': PROFILE_ORDER,
            'resume_only': True,
        })
        self.assertEqual(resume_response.status_code, 201, resume_response.get_json())
        self.assertEqual(resume_response.get_json()['participant_id'], session_data['participant_id'])
        self.assertEqual(resume_response.get_json()['study_stage'], 'post_evaluation')

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}, clear=False), patch(
            'routes.request_ai_reflection', return_value='Consider the performance evidence for each rating.'
        ):
            chat_response = returning_client.post('/api/ai_chat', json={
                'participant_id': session_data['participant_id'],
                'profile_id': 'it_2',
                'justification': 'The available performance evidence supports my initial evaluation.',
                'evaluation_context': {'profile_id': 'it_2'},
            })
        self.assertEqual(chat_response.status_code, 200, chat_response.get_json())

    def test_refresh_resumes_the_active_direct_participant_session(self):
        self.client.get('/')
        session_data = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': PROFILE_ORDER,
        }).get_json()
        initial_response = self.client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
            session_data['participant_id'], 'it_2', 1
        ))
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())

        self.assertEqual(self.client.get('/').status_code, 200)
        resumed_response = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': list(reversed(PROFILE_ORDER)),
        })

        self.assertEqual(resumed_response.status_code, 201, resumed_response.get_json())
        self.assertEqual(resumed_response.get_json()['participant_id'], session_data['participant_id'])
        self.assertEqual(resumed_response.get_json()['study_stage'], 'post_evaluation')

    def test_session_replaces_an_incomplete_active_participant(self):
        with self.app.app_context():
            incomplete_participant = Participant(status='started')
            db.session.add(incomplete_participant)
            db.session.commit()
            incomplete_participant_id = incomplete_participant.id

        with self.client.session_transaction() as session:
            session['participant_id'] = incomplete_participant_id

        response = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': PROFILE_ORDER,
        })

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertNotEqual(response.get_json()['participant_id'], incomplete_participant_id)
        self.assertEqual(response.get_json()['profile_order'], PROFILE_ORDER)

    def test_participant_api_rejects_a_foreign_participant_identifier(self):
        session_data = self.start_prolific_session()
        other_client = self.app.test_client()
        response = other_client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
            session_data['participant_id'], 'it_2', 1
        ))
        self.assertEqual(response.status_code, 401)
        with self.app.app_context():
            self.assertEqual(InitialEvaluation.query.count(), 0)

    def test_final_recall_rejects_non_object_scores(self):
        session_data = self.start_prolific_session()
        self.save_all_trials(session_data['participant_id'])
        response = self.client.post('/api/save_final_recall', json={
            'participant_id': session_data['participant_id'],
            'recalled_performance_scores': [91, 26, 89, 31],
            'recalled_performance_categories': PROFILE_CATEGORIES,
        })
        self.assertEqual(response.status_code, 400)

    def test_admin_export_requires_login_and_neutralizes_csv_formulas(self):
        session_data = self.start_prolific_session()
        self.save_all_trials(session_data['participant_id'])
        with self.app.app_context():
            participant = db.session.get(Participant, session_data['participant_id'])
            participant.demand_awareness = '=HYPERLINK("https://example.test")'
            participant.rating_change_reason = '+formula'
            db.session.commit()

        self.assertEqual(self.client.get('/export_csv').status_code, 401)
        with patch.dict('os.environ', {'ADMIN_API_KEY': 'test-admin-key'}, clear=False):
            login_response = self.client.post('/api/admin/login', json={'admin_key': 'test-admin-key'})
            self.assertEqual(login_response.status_code, 200, login_response.get_json())
            export_response = self.client.get('/export_csv')
        self.assertEqual(export_response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(export_response.get_data(as_text=True).lstrip('\ufeff'))))
        self.assertEqual(rows[0]['demand_awareness'], "'=HYPERLINK(\"https://example.test\")")
        self.assertEqual(rows[0]['rating_change_reason'], "'+formula")

    def test_ai_condition_requires_a_reflection_message(self):
        session_data = self.start_prolific_session()
        with self.app.app_context():
            participant = db.session.get(Participant, session_data['participant_id'])
            participant.experimental_condition = 'ai_assisted'
            db.session.commit()

        initial_payload = self.valid_initial_payload(session_data['participant_id'], 'it_2', 1)
        initial_response = self.client.post('/api/save_initial_evaluation', json=initial_payload)
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())
        payload = self.valid_final_payload(session_data['participant_id'], 'it_2', 1)
        missing_reflection = self.client.post('/api/save_trial', json=payload)
        self.assertEqual(missing_reflection.status_code, 400)

        payload['ai_conversation'] = '[{"role":"user","content":"justification"},{"role":"assistant","content":"reflection"},{"role":"user","content":"I reconsidered the evidence and retained my evaluations."}]'
        forged_conversation_response = self.client.post('/api/save_trial', json=payload)
        self.assertEqual(forged_conversation_response.status_code, 400)
        with self.app.app_context():
            db.session.add(AIConversation(
                participant_id=session_data['participant_id'],
                profile_id='it_2',
                request_count=2,
                messages=[
                    {'role': 'user', 'content': 'The available evidence supports this considered evaluation of the candidate.'},
                    {'role': 'assistant', 'content': 'Consider whether each rating is supported by the available evidence.'},
                    {'role': 'user', 'content': 'OK'},
                    {'role': 'assistant', 'content': 'That is a reasonable way to distinguish evidence from assumptions.'},
                ],
            ))
            db.session.commit()
        saved_response = self.client.post('/api/save_trial', json=payload)
        self.assertEqual(saved_response.status_code, 201, saved_response.get_json())

    def test_ai_chat_limits_messages_and_uses_server_owned_history(self):
        session_data = self.start_prolific_session()
        with self.app.app_context():
            participant = db.session.get(Participant, session_data['participant_id'])
            participant.experimental_condition = 'ai_assisted'
            db.session.commit()
        initial_response = self.client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
            session_data['participant_id'], 'it_2', 1
        ))
        self.assertEqual(initial_response.status_code, 201, initial_response.get_json())

        base_payload = {
            'participant_id': session_data['participant_id'],
            'profile_id': 'it_2',
            'evaluation_context': {'profile_id': 'it_2'},
        }
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}, clear=False), patch(
            'routes.request_ai_reflection', side_effect=[
                'First reflection.', 'Second reflection.', 'Third reflection.',
                'Fourth reflection.', 'Fifth reflection.',
            ]
        ):
            first_response = self.client.post('/api/ai_chat', json={
                **base_payload,
                'justification': 'Brief justification.',
            })
            self.assertEqual(first_response.status_code, 200, first_response.get_json())
            self.assertEqual(len(first_response.get_json()['conversation']), 2)

            short_message_response = self.client.post('/api/ai_chat', json={**base_payload, 'message': 'OK'})
            self.assertEqual(short_message_response.status_code, 200, short_message_response.get_json())
            self.assertEqual(len(short_message_response.get_json()['conversation']), 4)

            for message in (
                'I want to consider whether the performance record should affect each of my ratings.',
                'I am comparing my original judgments with the performance evidence shown in the profile.',
                'I have reviewed the distinction between performance, leadership, and promotability.',
            ):
                response = self.client.post('/api/ai_chat', json={**base_payload, 'message': message})
                self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(len(response.get_json()['conversation']), 10)

            limit_response = self.client.post('/api/ai_chat', json={
                **base_payload,
                'message': 'I would like another response even though the reflection limit has been reached.',
            })
            self.assertEqual(limit_response.status_code, 429)

    def test_placeholder_completion_configuration_does_not_redirect_participants(self):
        participant = SimpleNamespace(recruitment_source='prolific')
        with patch.dict('os.environ', {
            'PROLIFIC_COMPLETION_URL': '',
            'PROLIFIC_COMPLETION_CODE': 'your-prolific-completion-code',
        }, clear=False):
            self.assertIsNone(get_completion_url(participant))

    def test_prolific_sessions_are_isolated_and_complete_with_the_configured_code(self):
        second_client = self.app.test_client()
        self.client.get('/?PROLIFIC_PID=participant-a&STUDY_ID=study-1&SESSION_ID=session-a')
        second_client.get('/?PROLIFIC_PID=participant-b&STUDY_ID=study-1&SESSION_ID=session-b')
        first_session = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': PROFILE_ORDER,
        }).get_json()
        second_session = second_client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': list(reversed(PROFILE_ORDER)),
        }).get_json()

        self.assertNotEqual(first_session['participant_id'], second_session['participant_id'])
        with self.app.app_context():
            participant = db.session.get(Participant, first_session['participant_id'])
            participant.experimental_condition = 'control'
            db.session.commit()
        foreign_save = second_client.post('/api/save_initial_evaluation', json=self.valid_initial_payload(
            first_session['participant_id'], 'it_2', 1
        ))
        self.assertEqual(foreign_save.status_code, 401, foreign_save.get_json())

        second_initial_payload = self.valid_initial_payload(second_session['participant_id'], 'sales_5', 1)
        second_initial_payload['bonus_allocation'] = 1500
        second_initial_save = second_client.post('/api/save_initial_evaluation', json=second_initial_payload)
        self.assertEqual(second_initial_save.status_code, 201, second_initial_save.get_json())

        self.save_all_trials(first_session['participant_id'])
        recall_response = self.client.post('/api/save_final_recall', json={
            'participant_id': first_session['participant_id'],
            'recalled_performance_scores': PROFILE_SCORES,
            'recalled_performance_categories': PROFILE_CATEGORIES,
        })
        self.assertEqual(recall_response.status_code, 200, recall_response.get_json())
        with patch.dict('os.environ', {'PROLIFIC_COMPLETION_CODE': 'test-completion-code'}, clear=False):
            finish_response = self.client.post('/api/finish_session', json={
                'participant_id': first_session['participant_id'],
                'demand_awareness': 'The study examines workplace candidate evaluations.',
                'rating_change_reason': 'Performance information influenced some ratings.',
                **FINAL_DEMOGRAPHICS,
            })

        self.assertEqual(finish_response.status_code, 200, finish_response.get_json())
        self.assertEqual(
            finish_response.get_json()['completion_url'],
            'https://app.prolific.com/submissions/complete?cc=test-completion-code',
        )
        with self.app.app_context():
            self.assertEqual(Trial.query.filter_by(participant_id=first_session['participant_id']).count(), 4)
            self.assertEqual(Trial.query.filter_by(participant_id=second_session['participant_id']).count(), 0)
            self.assertEqual(
                InitialEvaluation.query.filter_by(participant_id=second_session['participant_id']).one().bonus_allocation,
                1500,
            )

    def test_complete_flow_resumes_recall_then_questionnaire_and_exports_stable_csv(self):
        session_data = self.start_prolific_session()
        self.save_all_trials(session_data['participant_id'])

        resume_recall = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': list(reversed(PROFILE_ORDER)),
        })
        self.assertEqual(resume_recall.status_code, 201, resume_recall.get_json())
        self.assertEqual(resume_recall.get_json()['study_stage'], 'final_recall')
        self.assertEqual(resume_recall.get_json()['profile_order'], PROFILE_ORDER)

        recall_response = self.client.post('/api/save_final_recall', json={
            'participant_id': session_data['participant_id'],
            'recalled_performance_scores': PROFILE_SCORES,
            'recalled_performance_categories': PROFILE_CATEGORIES,
        })
        self.assertEqual(recall_response.status_code, 200, recall_response.get_json())

        resume_questionnaire = self.client.post('/api/init_session', json={
            'consent_accepted': True,
            'profile_order': PROFILE_ORDER,
        })
        self.assertEqual(resume_questionnaire.status_code, 201, resume_questionnaire.get_json())
        self.assertEqual(resume_questionnaire.get_json()['study_stage'], 'final_questionnaire')

        finish_response = self.client.post('/api/finish_session', json={
            'participant_id': session_data['participant_id'],
            'demand_awareness': 'The study examines workplace candidate evaluations.',
            'rating_change_reason': 'Performance information influenced some ratings.',
            **FINAL_DEMOGRAPHICS,
        })
        self.assertEqual(finish_response.status_code, 200, finish_response.get_json())

        with self.client.session_transaction() as session:
            session['is_admin'] = True
        export_response = self.client.get('/export_csv')
        self.assertEqual(export_response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(export_response.get_data(as_text=True).lstrip('\ufeff'))))
        self.assertEqual(len(rows), 4)
        self.assertEqual([row['trial_order'] for row in rows], ['1', '2', '3', '4'])
        self.assertEqual([row['profile_id'] for row in rows], PROFILE_ORDER)
        self.assertEqual(len({row['profile_id'] for row in rows}), 4)
        self.assertTrue(all(row['recalled_performance_score'] for row in rows))
        self.assertTrue(all(row['recalled_performance_category'] for row in rows))
        self.assertEqual(rows[0]['demographic_age'], str(FINAL_DEMOGRAPHICS['demographic_age']))
        self.assertEqual(rows[0]['demographic_years_experience'], str(FINAL_DEMOGRAPHICS['demographic_years_experience']))
        self.assertEqual(rows[0]['demographic_leadership_position'], FINAL_DEMOGRAPHICS['demographic_leadership_position'])
        self.assertEqual(rows[0]['demographic_nationality'], FINAL_DEMOGRAPHICS['demographic_nationality'])
        self.assertEqual(rows[0]['technical_difficulties'], FINAL_DEMOGRAPHICS['technical_difficulties'])


if __name__ == '__main__':
    unittest.main()
