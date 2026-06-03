import os
import sys
from flask import Flask
from .config import Config
from .extensions import db, login_manager, migrate


def create_app():
    # Detect PyInstaller frozen mode — templates/static are bundled into _MEIPASS
    if getattr(sys, 'frozen', False):
        template_folder = os.path.join(sys._MEIPASS, 'app', 'templates')
        static_folder = os.path.join(sys._MEIPASS, 'app', 'static')
    else:
        # Normal Python run: templates/ and static/ are relative to this file
        package_dir = os.path.dirname(os.path.abspath(__file__))
        template_folder = os.path.join(package_dir, 'templates')
        static_folder = os.path.join(package_dir, 'static')

    app = Flask(__name__,
                template_folder=template_folder,
                static_folder=static_folder)

    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录后再访问。'

    # Register blueprints
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from .editor import bp as editor_bp
    app.register_blueprint(editor_bp)

    # Ensure upload directory exists
    upload_dir = app.config.get('UPLOAD_FOLDER', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    with app.app_context():
        from . import models  # noqa: ensure models are loaded

    # CLI command: flask create-admin
    @app.cli.command('create-admin')
    def create_admin():
        """Create the initial admin user."""
        from .models import User
        with app.app_context():
            db.create_all()
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', email='admin@example.com', is_admin=True)
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()
                print('Admin user created: admin / admin123')
            else:
                print('Admin user already exists')

    return app
