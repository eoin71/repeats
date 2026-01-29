from flask_sqlalchemy import SQLAlchemy
from datetime import date

db = SQLAlchemy()

class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    active = db.Column(db.Boolean, default=True)

    completions = db.relationship('TaskCompletion', backref='task', cascade='all, delete-orphan')

    def is_completed_today(self):
        """Check if this task has been completed today."""
        today = date.today()
        return any(c.completion_date == today for c in self.completions)


class TaskCompletion(db.Model):
    __tablename__ = 'task_completions'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    completion_date = db.Column(db.Date, nullable=False, default=date.today)
    completed_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    __table_args__ = (
        db.UniqueConstraint('task_id', 'completion_date', name='unique_task_date'),
    )
