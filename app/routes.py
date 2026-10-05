from flask import Blueprint, render_template, request
from app.models import db, Task, TaskCompletion, Countdown, ALL_DAYS, TIMES_OF_DAY
from app import intervals, quotes, strava, weather
from datetime import date, datetime, timedelta

bp = Blueprint('main', __name__)


def _group_by_time_of_day(tasks):
    """Split tasks into (heading, tasks) groups by time of day.

    Headings are only used when at least one task is tagged; untagged tasks
    go under afternoon. Otherwise a single group with no heading is returned.
    """
    if not any(t.time_of_day for t in tasks):
        return [(None, tasks)]

    groups = []
    for time in TIMES_OF_DAY:
        group = [t for t in tasks if (t.time_of_day or 'afternoon') == time]
        if group:
            groups.append((time, group))
    return groups


@bp.route('/')
def index():
    """Display all active tasks and completion history."""
    all_tasks = Task.query.filter_by(active=True).order_by(Task.created_at.desc()).all()
    today = date.today()
    tasks = [t for t in all_tasks if t.is_scheduled(today)]
    other_tasks = [t for t in all_tasks if not t.is_scheduled(today)]
    history = Task.get_completion_history(days=7)
    countdowns = Countdown.query.filter_by(active=True).order_by(Countdown.target_date.asc()).all()
    return render_template(
        'index.html',
        tasks=tasks,
        task_groups=_group_by_time_of_day(tasks),
        other_tasks=other_tasks,
        history=history,
        countdowns=countdowns,
    )


@bp.route('/quote')
def quote():
    """Render a random stoic quote fragment (loaded async via HTMX)."""
    return render_template('_quote.html', quote=quotes.get_quote())


@bp.route('/weather')
def weather_widget():
    """Render today's cycleability and weather (loaded async via HTMX)."""
    return render_template(
        '_weather_widget.html',
        forecast=weather.next_forecast(),
        today=datetime.now(weather.TZ).date(),
    )


@bp.route('/workouts')
def workouts():
    """Render this week's workout plan fragment (loaded async via HTMX)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]
    # Today first; earlier days this week wrap to the end of the stack
    today_idx = today.weekday()
    week_dates = week_dates[today_idx:] + week_dates[:today_idx]
    events = intervals.get_week_events(monday)
    if events is not None:
        rides = strava.get_week_rides(monday) or []
        unplanned = strava.match_rides(
            events, rides, lambda e: e['type'] in weather.CYCLING_TYPES or e['type'] == 'VirtualRide'
        )
        # Rides with no planned workout get their own entry
        for ride in unplanned:
            events.append({
                'date': ride['date'], 'start': ride['start'], 'name': ride['name'], 'type': ride['type'],
                'duration': None, 'load': None, 'description': '', 'category': None, 'ride': ride,
                'unplanned': True,
            })
        events.sort(key=lambda e: (e['date'] or today, e['start'] or datetime.min))
        for event in events:
            if event.get('ride'):
                event['completed'] = True
            event['weather'] = weather.activity_score(event)
    return render_template(
        '_workout_week.html',
        week_dates=week_dates,
        events=events,
        today=today,
    )


def _chart_paths(series):
    """Build SVG paths for the fitness area and fatigue line from a series.

    Returns a dict with the area path, line path and viewBox size, or None if
    there are not enough points to plot.
    """
    if not series or len(series) < 2:
        return None

    width, height = 320.0, 135.0
    pad_x, pad_top, pad_bottom = 4.0, 12.0, 10.0

    values = [s['fitness'] for s in series] + [s['fatigue'] for s in series]
    top = max(values) * 1.15
    if top <= 0:
        top = 1.0

    inner_w = width - 2 * pad_x
    inner_h = height - pad_top - pad_bottom
    n = len(series)

    def x(i):
        return pad_x + inner_w * i / (n - 1)

    def y(v):
        return pad_top + inner_h - inner_h * v / top

    fitness = [(x(i), y(s['fitness'])) for i, s in enumerate(series)]
    fatigue = [(x(i), y(s['fatigue'])) for i, s in enumerate(series)]

    area = (
        f"M {fitness[0][0]:.1f} {fitness[0][1]:.1f} "
        + ' '.join(f"L {px:.1f} {py:.1f}" for px, py in fitness[1:])
        + f" L {fitness[-1][0]:.1f} {height - pad_bottom:.1f}"
        + f" L {fitness[0][0]:.1f} {height - pad_bottom:.1f} Z"
    )
    line = (
        f"M {fatigue[0][0]:.1f} {fatigue[0][1]:.1f} "
        + ' '.join(f"L {px:.1f} {py:.1f}" for px, py in fatigue[1:])
    )

    return {'area': area, 'line': line, 'width': width, 'height': height}


@bp.route('/fitness')
def fitness():
    """Render the fitness/fatigue widget fragment (loaded async via HTMX)."""
    series = intervals.get_wellness_series(days=42)
    latest = series[-1] if series else None
    previous = series[-2] if series and len(series) > 1 else None
    chart = _chart_paths(series)
    return render_template(
        '_fitness_widget.html',
        latest=latest,
        previous=previous,
        chart=chart,
    )


@bp.route('/tasks', methods=['POST'])
def create_task():
    """Create a new task and return its HTML fragment."""
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()

    # Selected weekdays (Monday=0); none selected means every day
    days = ''.join(sorted({d for d in request.form.getlist('days') if d in ALL_DAYS}))

    time_of_day = request.form.get('time_of_day') or None
    if time_of_day not in TIMES_OF_DAY:
        time_of_day = None

    if not title:
        return '', 400

    task = Task(title=title, description=description, days=days or ALL_DAYS, time_of_day=time_of_day)
    db.session.add(task)
    db.session.commit()

    today = date.today()
    if not task.is_scheduled(today):
        # Not due today, so it belongs in the "other days" section; reload the page
        return '', 200, {'HX-Refresh': 'true'}

    todays_tasks = [t for t in Task.query.filter_by(active=True).all() if t.is_scheduled(today)]
    if any(t.time_of_day for t in todays_tasks):
        # Today's list is grouped by time of day, so reload to place it under the right heading
        return '', 200, {'HX-Refresh': 'true'}

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
