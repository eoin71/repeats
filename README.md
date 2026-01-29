# Repeats

A simple, single-user web application for tracking daily repeating tasks. Tasks automatically reset each day, making it perfect for maintaining daily habits and routines.

## Features

- **Daily Task Management**: Create tasks that automatically reset every day
- **Simple Interface**: Clean, minimal design focused on task completion
- **Task Completion Tracking**: Mark tasks as complete with a single click
- **Persistent History**: All completion data is stored for potential future analytics
- **Dark Mode**: Automatically adapts to your system's color scheme preference
- **Responsive Design**: Works seamlessly on desktop and mobile devices

## Technology Stack

- **Backend**: Flask (Python web framework)
- **Database**: SQLite (lightweight, file-based database)
- **Frontend**: HTMX for dynamic interactions without JavaScript
- **Styling**: Tailwind CSS with custom color palette
- **Font**: Google Sans Code
- **Server**: Gunicorn for production deployment

## Requirements

- Python 3.14 or higher
- Docker (for containerized deployment)

## Local Development

### Installation

1. Clone the repository:
```bash
git clone https://github.com/eoin71/repeats
cd repeats
```

2. Install dependencies using uv:
```bash
uv add flask
uv add flask-sqlalchemy
uv add gunicorn
```

### Running Locally

Start the development server:
```bash
uv run python run.py
```

The application will be available at `http://localhost:5000`

## Docker Deployment

### Building the Docker Image

Build the Docker image:
```bash
docker build -t repeats-app .
```

### Running with Docker

Run the container:
```bash
docker run -d -p 5000:5000 -v ./instance:/app/instance --name repeats repeats-app
```

The `-v ./instance:/app/instance` flag mounts a volume to persist your SQLite database on the host machine.

### Running with Docker Compose

For easier management, use Docker Compose:

1. Start the application:
```bash
docker-compose up -d
```

2. View logs:
```bash
docker-compose logs -f
```

3. Stop the application:
```bash
docker-compose down
```

The application will be available at `http://localhost:5000`

## How It Works

### Daily Reset Logic

The app uses a date-based completion system:

- Each task has a permanent record in the `tasks` table
- When you mark a task as complete, a record is created in the `task_completions` table with today's date
- The app checks if a completion record exists for today's date to determine if a task is complete
- Tomorrow, when the date changes, no completion record exists for the new date, so tasks appear incomplete again
- All historical completion data is preserved

### Database Schema

**tasks table:**
- `id`: Primary key
- `title`: Task name
- `description`: Optional task details
- `created_at`: Creation timestamp
- `active`: Boolean for soft deletes

**task_completions table:**
- `id`: Primary key
- `task_id`: Foreign key to tasks
- `completion_date`: Date the task was completed (DATE type)
- `completed_at`: Timestamp when marked complete
- Unique constraint on (task_id, completion_date) prevents duplicate completions

## Project Structure

```
repeats/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── models.py            # Database models
│   ├── database.py          # Database initialization
│   ├── routes.py            # HTTP endpoints
│   ├── templates/           # HTML templates
│   │   ├── base.html        # Base template with styling
│   │   ├── index.html       # Main page
│   │   └── _task_item.html  # Task card component
│   └── static/              # Static files (optional)
├── instance/                # SQLite database location (gitignored)
├── run.py                   # Application entry point
├── Dockerfile               # Docker configuration
├── docker-compose.yml       # Docker Compose configuration
└── pyproject.toml          # Python dependencies
```

## Configuration

### Environment Variables

- `FLASK_APP`: Set to `run.py` (default in production)
- `FLASK_ENV`: Set to `production` for deployment

### Gunicorn Settings

The production deployment uses Gunicorn with:
- 4 worker processes
- 120-second timeout
- Binding to `0.0.0.0:5000`

## Data Persistence

The SQLite database is stored in the `instance/` directory. When running with Docker, make sure to mount this directory as a volume to prevent data loss when containers are recreated:

```bash
-v ./instance:/app/instance
```

## Customization

### Changing Colors

The color palette is defined in `app/templates/base.html` in the Tailwind configuration. You can customize the primary, secondary, accent, and danger colors by modifying the color values in the `tailwind.config` object.

### Modifying Task Behavior

To change how tasks reset (e.g., weekly instead of daily), modify the `is_completed_today()` method in `app/models.py` and adjust the date comparison logic in `app/routes.py`.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
