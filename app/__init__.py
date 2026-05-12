from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    # Use /data directory on Render (persistent), or local instance/ for dev
    base_dir = os.environ.get('RENDER_DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance'))
    os.makedirs(base_dir, exist_ok=True)
    db_path = os.path.join(base_dir, 'project.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

    db.init_app(app)

    from . import routes
    app.register_blueprint(routes.bp)

    with app.app_context():
        db.create_all()

    return app
