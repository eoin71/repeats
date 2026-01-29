from flask import Blueprint, render_template, request
from app.models import db, Task, TaskCompletion
from datetime import date

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Display all active tasks."""
    tasks = Task.query.filter_by(active=True).order_by(Task.created_at.desc()).all()
    return render_template('index.html', tasks=tasks)


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
