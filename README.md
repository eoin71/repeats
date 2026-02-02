![App Screenshot](images/screenshot.png)


# Repeats

A simple, single-user web application for tracking daily repeating tasks. Tasks automatically reset each day, making it perfect for maintaining daily habits and routines.

## Features

- **Daily Task Management**: Create tasks that automatically reset every day
- **Simple Interface**: Clean, minimal design focused on task completion
- **Task Completion Tracking**: Mark tasks as complete with a single click
- **Persistent History**: All completion data is stored for potential future analytics
- **Dark Mode**: Automatically adapts to your system's color scheme preference
- **Responsive Design**: Works seamlessly on desktop and mobile devices
- **History**: Shows the last 7 days of task history


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

### Quick Start (Production)

The easiest way to deploy is using the pre-built Docker Hub image:

1. Download the production docker-compose file or create `docker-compose.prod.yml`:
```yaml
version: '3.8'

services:
  web:
    image: eoin71/repeats:latest
    ports:
      - "5000:5000"
    volumes:
      - repeats-data:/app/instance
    environment:
      - FLASK_APP=run.py
      - FLASK_ENV=production
    restart: unless-stopped

volumes:
  repeats-data:
```

2. Start the application:
```bash
docker-compose -f docker-compose.prod.yml up -d
```

The application will be available at `http://localhost:5000`

**Benefits:**
- No build required - pulls pre-built multi-platform image (supports amd64 and arm64)
- Faster deployment
- Consistent across all environments
- Automatic updates by pulling latest image

### Development/Local Deployment

For local development or building from source:

1. Build and run with Docker Compose:
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

### Manual Docker Build

If you want to build the image yourself:

```bash
docker build -t repeats-app .
docker run -d -p 5000:5000 -v repeats-data:/app/instance --name repeats repeats-app
```

### Multi-Platform Builds

To build for multiple architectures (amd64, arm64):

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t your-username/repeats:latest --push .
```

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
├── docker-compose.yml       # Development Docker Compose
├── docker-compose.prod.yml  # Production Docker Compose (Docker Hub)
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

The SQLite database is stored in the `instance/` directory.

**Docker Volumes:**
- **Production (docker-compose.prod.yml)**: Uses a named Docker volume `repeats-data` for automatic management and portability
- **Development (docker-compose.yml)**: Uses a named Docker volume for consistent behavior
- **Manual runs**: Use `-v repeats-data:/app/instance` or bind mount with `-v ./instance:/app/instance`

Named volumes are recommended as they:
- Handle permissions correctly across platforms
- Are managed by Docker
- Work consistently on all operating systems
- Survive container deletion

To backup your data:
```bash
docker run --rm -v repeats-data:/data -v $(pwd):/backup alpine tar czf /backup/repeats-backup.tar.gz -C /data .
```

To restore from backup:
```bash
docker run --rm -v repeats-data:/data -v $(pwd):/backup alpine tar xzf /backup/repeats-backup.tar.gz -C /data
```

## Customization

### Changing Colors

The color palette is defined in `app/templates/base.html` in the Tailwind configuration. You can customize the primary, secondary, accent, and danger colors by modifying the color values in the `tailwind.config` object.

### Modifying Task Behavior

To change how tasks reset (e.g., weekly instead of daily), modify the `is_completed_today()` method in `app/models.py` and adjust the date comparison logic in `app/routes.py`.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
