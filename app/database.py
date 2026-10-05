from sqlalchemy import inspect, text

from app.models import db, ALL_DAYS


def init_db(app):
    """Initialize the database with the Flask app."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _add_missing_columns()


def _add_missing_columns():
    """Add columns introduced after a table was first created.

    create_all() only creates missing tables, so existing databases need new
    columns added by hand.
    """
    new_task_columns = {
        'days': f"VARCHAR(7) NOT NULL DEFAULT '{ALL_DAYS}'",
        'time_of_day': 'VARCHAR(10)',
    }
    task_columns = {c['name'] for c in inspect(db.engine).get_columns('tasks')}
    with db.engine.begin() as conn:
        for name, definition in new_task_columns.items():
            if name not in task_columns:
                conn.execute(text(f'ALTER TABLE tasks ADD COLUMN {name} {definition}'))
