from app import create_app

# Create the Flask app instance
# This is used by both gunicorn (production) and Flask dev server
app = create_app()

if __name__ == '__main__':
    # Development server only
    app.run(debug=True, host='0.0.0.0', port=5000)
