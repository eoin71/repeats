from flask_sqlalchemy import SQLAlchemy
from datetime import date, timedelta, datetime

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

    @classmethod
    def get_completion_history(cls, days=7):
        """Get completion status for the last N days.

        Returns list of dicts with date, completion status, and task details.
        A day is marked complete if all tasks that existed on that day were completed.
        Tasks are only counted for days on or after their creation date.
        """
        today = date.today()
        history = []

        for i in range(days - 1, -1, -1):  # Go backwards from today
            check_date = today - timedelta(days=i)

            # Get all active tasks that existed on this date
            # Convert check_date to datetime for comparison with created_at
            check_datetime = datetime.combine(check_date, datetime.min.time())

            tasks_on_date = cls.query.filter(
                cls.active == True,
                cls.created_at <= check_datetime
            ).all()

            if not tasks_on_date:
                # Skip days with no tasks
                continue

            # Build list of tasks with their completion status
            task_details = []
            for task in tasks_on_date:
                was_completed = any(c.completion_date == check_date for c in task.completions)
                task_details.append({
                    'title': task.title,
                    'completed': was_completed
                })

            # Check if all tasks were completed on this date
            all_completed = all(t['completed'] for t in task_details)

            history.append({
                'date': check_date,
                'completed': all_completed,
                'total_tasks': len(tasks_on_date),
                'tasks': task_details
            })

        return history


class TaskCompletion(db.Model):
    __tablename__ = 'task_completions'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    completion_date = db.Column(db.Date, nullable=False, default=date.today)
    completed_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    __table_args__ = (
        db.UniqueConstraint('task_id', 'completion_date', name='unique_task_date'),
    )
