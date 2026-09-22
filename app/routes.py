from flask import Blueprint, render_template, request
from app.models import db, Task, TaskCompletion, Countdown
from datetime import date, datetime

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Display all active tasks and completion history."""
    tasks = Task.query.filter_by(active=True).order_by(Task.created_at.desc()).all()
    history = Task.get_completion_history(days=7)
    countdowns = Countdown.query.filter_by(active=True).order_by(Countdown.target_date.asc()).all()
    return render_template('index.html', tasks=tasks, history=history, countdowns=countdowns)


@bp.route('/tasks', methods=['POST'])
def create_task():
    """Create a new task and return its HTML fragment."""
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()

    if not title:
        return '', 400

    task = Task(title=title, description=description)
    db.session.add(task)
    db.session.commit()

    # Return HTML fragment for HTMX to insert
    return render_template('_task_item.html', task=task)


@bp.route('/tasks/<int:task_id>/toggle', methods=['POST'])
def toggle_task(task_id):
    """Toggle task completion status for today."""
    task = Task.query.get_or_404(task_id)
    today = date.today()

    # Check if completed today
    completion = TaskCompletion.query.filter_by(
        task_id=task_id,
        completion_date=today
    ).first()

    if completion:
        # Uncomplete: delete the completion record
        db.session.delete(completion)
    else:
        # Complete: create a new completion record
        completion = TaskCompletion(task_id=task_id, completion_date=today)
        db.session.add(completion)

    db.session.commit()

    # Return updated task HTML fragment
    return render_template('_task_item.html', task=task)


@bp.route('/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Soft delete a task."""
    task = Task.query.get_or_404(task_id)
    task.active = False
    db.session.commit()
    # Return empty content for HTMX to swap (removes the element)
    return '', 200


@bp.route('/countdowns', methods=['POST'])
def create_countdown():
    """Create a new countdown and return its HTML fragment."""
    title = request.form.get('title', '').strip()
    target_date_str = request.form.get('target_date', '').strip()

    if not title or not target_date_str:
        return '', 400

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return '', 400

    countdown = Countdown(title=title, target_date=target_date)
    db.session.add(countdown)
    db.session.commit()

    return render_template('_countdown_item.html', countdown=countdown)


@bp.route('/countdowns/<int:countdown_id>', methods=['DELETE'])
def delete_countdown(countdown_id):
    """Soft delete a countdown."""
    countdown = Countdown.query.get_or_404(countdown_id)
    countdown.active = False
    db.session.commit()
    return '', 200
