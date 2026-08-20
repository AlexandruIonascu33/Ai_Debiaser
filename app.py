import logging
import os
import time
import uuid
from datetime import timedelta

import click
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from sqlalchemy import inspect, text
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from extensions import db, limiter, migrate
from routes import main
from utils import get_missing_production_settings


def create_app(test_config=None):
    """Create and configure the Pre-Rating experiment application."""
    app = Flask(__name__)
    if test_config is not None:
        app.config.from_mapping(
            APP_ENV='testing',
            SECRET_KEY='test-secret-key',
            PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_COOKIE_SECURE=False,
            TESTING=True,
        )
        app.config.update(test_config)
    else:
        app_env = os.environ.get('APP_ENV', 'development')
        app.config['APP_ENV'] = app_env
        app.config['SECRET_KEY'] = os.environ.get('ADMIN_SECRET_KEY', 'dev-key-change-in-production')
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['SESSION_COOKIE_SECURE'] = app_env != 'development'

        if app_env == 'development':
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pre-rating-local.db'
            print('INFO: Development environment detected. Using local database: pre-rating-local.db')
        else:
            raw_db_url = os.environ.get('DATABASE_URL', '')
            if not raw_db_url.startswith('postgres'):
                raise ValueError('DATABASE_URL for PostgreSQL is not configured correctly in production.')
            clean_url = raw_db_url.replace('postgresql+pg8000://', '').replace('postgresql://', '').replace('postgres://', '')
            app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql+pg8000://{clean_url}'
            missing_settings = get_missing_production_settings()
            if missing_settings:
                raise ValueError(f"Production configuration requires real values for: {', '.join(missing_settings)}.")
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config.setdefault('AI_CHAT_RATE_LIMIT', os.environ.get('AI_CHAT_RATE_LIMIT', '30 per hour'))
    app.config.setdefault('REQUIRE_PROLIFIC_METADATA', app.config['APP_ENV'] == 'production')
    app.config.setdefault('MAX_CONTENT_LENGTH', 64 * 1024)
    app.config.setdefault('RATELIMIT_STORAGE_URI', os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'))
    if app.config['APP_ENV'] == 'production' and app.config['RATELIMIT_STORAGE_URI'] == 'memory://':
        app.logger.warning('RATELIMIT_STORAGE_URI is not configured; AI IP rate limits are local to each app instance.')

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    app.register_blueprint(main)

    logging.basicConfig(
        level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )

    @app.before_request
    def start_request_logging():
        g.request_id = uuid.uuid4().hex
        g.request_started_at = time.perf_counter()

    @app.after_request
    def finish_request_logging(response):
        elapsed_ms = round((time.perf_counter() - g.get('request_started_at', time.perf_counter())) * 1000)
        response.headers['X-Request-ID'] = g.get('request_id', '')
        if not request.path.startswith('/static/'):
            app.logger.info(
                'request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s',
                g.get('request_id'), request.method, request.path, response.status_code, elapsed_ms
            )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception('unhandled_error request_id=%s', g.get('request_id'))
        if request.path.startswith('/api/'):
            return jsonify({'status': 'error', 'message': 'A server error occurred. Please try again.'}), 500
        return 'Internal Server Error', 500

    with app.app_context():
        if app.config['APP_ENV'] in {'development', 'testing'} and app.config.get('AUTO_CREATE_SCHEMA', True):
            db.create_all()
            ensure_schema_columns()

    @app.cli.command('reset-local-db')
    @click.option('--confirm', is_flag=True, help='Required because this permanently deletes local study data.')
    def reset_local_db(confirm):
        """Recreate the local SQLite study database from the current models."""
        if not confirm:
            raise click.UsageError('Pass --confirm to delete and recreate the local database.')
        if not str(db.engine.url).startswith('sqlite'):
            raise click.UsageError('This command only permits SQLite databases.')
        db.drop_all()
        db.create_all()
        click.echo('Local database recreated from the current models.')

    return app


def ensure_schema_columns():
    """Add additive columns for installations created before the current model."""
    trial_columns = {column['name'] for column in inspect(db.engine).get_columns('trials')}
    missing_trial_columns = {
        'performance_recall_error': 'INTEGER',
        'recalled_performance_category': 'VARCHAR(32)',
        'submission_id': 'VARCHAR(64)',
        'post_reaction_time_ms': 'INTEGER',
    }
    with db.engine.begin() as connection:
        for column_name, column_type in missing_trial_columns.items():
            if column_name not in trial_columns:
                connection.execute(text(f'ALTER TABLE trials ADD COLUMN {column_name} {column_type}'))

    participant_columns = {column['name'] for column in inspect(db.engine).get_columns('participants')}
    missing_columns = {
        'study_version': "VARCHAR(32) NOT NULL DEFAULT '1.0.0'",
        'experimental_condition': "VARCHAR(20) NOT NULL DEFAULT 'ai_assisted'",
        'resume_count': 'INTEGER NOT NULL DEFAULT 0',
        'rating_change_reason': 'TEXT',
        'technical_difficulties': 'TEXT',
        'ai_usefulness_1': 'INTEGER',
        'ai_usefulness_2': 'INTEGER',
        'ai_usefulness_3': 'INTEGER',
        'demographic_age_range': 'VARCHAR(32)',
        'demographic_age': 'INTEGER',
        'demographic_gender': 'VARCHAR(64)',
        'demographic_work_status': 'VARCHAR(64)',
        'demographic_work_field': 'VARCHAR(128)',
        'demographic_work_experience': 'VARCHAR(32)',
        'demographic_years_experience': 'INTEGER',
        'demographic_leadership_position': 'VARCHAR(32)',
        'demographic_nationality': 'VARCHAR(128)',
    }
    with db.engine.begin() as connection:
        for column_name, column_type in missing_columns.items():
            if column_name not in participant_columns:
                connection.execute(text(f'ALTER TABLE participants ADD COLUMN {column_name} {column_type}'))


app = create_app()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
