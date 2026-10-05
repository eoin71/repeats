from flask_sqlalchemy import SQLAlchemy
from datetime import date, timedelta, datetime

db = SQLAlchemy()

# Weekdays are stored as digits (Monday=0 ... Sunday=6), e.g. '024' = Mon/Wed/Fri
ALL_DAYS = '0123456'
DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

# Optional time-of-day tags, in display order; untagged tasks count as afternoon
TIMES_OF_DAY = ['morning', 'afternoon', 'evening']

class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    active = db.Column(db.Boolean, default=True)
    days = db.Column(db.String(7), nullable=False, default=ALL_DAYS, server_default=ALL_DAYS)
    time_of_day = db.Column(db.String(10))

    completions = db.relationship('TaskCompletion', backref='task', cascade='all, delete-orphan')

    def is_completed_today(self):
        """Check if this task has been completed today."""
        today = date.today()
        return any(c.completion_date == today for c in self.completions)

    def is_scheduled(self, day):
        """Check if this task is due on the given date."""
        return str(day.weekday()) in (self.days or ALL_DAYS)

    def schedule_label(self):
        """Short description of the task's days, or None if it's every day."""
        days = self.days or ALL_DAYS
        if days == ALL_DAYS:
            return None
        if days == '01234':
            return 'Weekdays'
        if days == '56':
            return 'Weekends'
        return ' · '.join(DAY_NAMES[int(d)] for d in days)

    def next_scheduled_day(self):
        """Name of the next day after today this task is due."""
        today = date.today()
        for offset in range(1, 8):
            day = today + timedelta(days=offset)
            if self.is_scheduled(day):
                return 'Tomorrow' if offset == 1 else DAY_NAMES[day.weekday()]
        return None

    def current_streak(self):
        """Count consecutive completed scheduled days up to today.

        Days the task isn't scheduled on are skipped. If today isn't completed
        yet, the streak counts back from the previous scheduled day so it isn't
        shown as broken until a scheduled day has been missed.
        """
        done = {c.completion_date for c in self.completions}
        if not done:
            return 0
        earliest = min(done)

        day = date.today()
        if day not in done:
            day -= timedelta(days=1)

        streak = 0
        while day >= earliest:
            if self.is_scheduled(day):
                if day not in done:
                    break
                streak += 1
            day -= timedelta(days=1)
        return streak

    @classmethod
    def get_completion_history(cls, days=7):
        """Get completion status for the last N days.

        Returns list of dicts with date, completion status, and task details.
        A day is marked complete if all tasks scheduled on that day were completed.
        Tasks are only counted for days on or after their creation date.
        """
        today = date.today()
        history = []

        for i in range(days - 1, -1, -1):  # Go backwards from today
            check_date = today - timedelta(days=i)

            # Get all active tasks that existed on this date
            # Convert check_date to datetime for comparison with created_at
            check_datetime = datetime.combine(check_date, datetime.min.time())

            tasks_on_date = [
                task for task in cls.query.filter(
                    cls.active == True,
                    cls.created_at <= check_datetime
                ).all()
                if task.is_scheduled(check_date)
            ]

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


class Countdown(db.Model):
    __tablename__ = 'countdowns'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    target_date = db.Column(db.Date, nullable=False)
    active = db.Column(db.Boolean, default=True)

    def days_remaining(self):
        return (self.target_date - date.today()).days


class TaskCompletion(db.Model):
    __tablename__ = 'task_completions'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    completion_date = db.Column(db.Date, nullable=False, default=date.today)
    completed_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    __table_args__ = (
        db.UniqueConstraint('task_id', 'completion_date', name='unique_task_date'),
    )


# Labels for the 1-5 note rating scales
MOOD_EMOJI = {1: '😞', 2: '🙁', 3: '😐', 4: '🙂', 5: '😄'}


class Note(db.Model):
    """A journal note about a day; a day can have many. Text and ratings are each optional."""
    __tablename__ = 'notes'

    id = db.Column(db.Integer, primary_key=True)
    note_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    text = db.Column(db.Text)
    mood = db.Column(db.Integer)          # 1 (bad) - 5 (great)
    performance = db.Column(db.Integer)   # 1 (bad) - 5 (great)

    @classmethod
    def day_summaries(cls, start, end):
        """Per-day note count and average ratings for start..end inclusive.

        Returns {date: {'count': int, 'mood': float|None, 'performance': float|None}}.
        """
        rows = db.session.query(
            cls.note_date,
            db.func.count(cls.id),
            db.func.avg(cls.mood),
            db.func.avg(cls.performance),
        ).filter(cls.note_date >= start, cls.note_date <= end).group_by(cls.note_date).all()
        return {
            day: {'count': count, 'mood': mood, 'performance': performance}
            for day, count, mood, performance in rows
        }
