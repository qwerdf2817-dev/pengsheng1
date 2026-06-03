import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')

    # Database: use DATABASE_URL env var if set, otherwise SQLite
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # Render provides postgres:// but SQLAlchemy needs postgresql://
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    else:
        db_url = 'sqlite:///' + os.path.join(basedir, '..', 'app.db')
    SQLALCHEMY_DATABASE_URI = db_url

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get(
        'UPLOAD_FOLDER',
        os.path.join(basedir, '..', 'uploads')
    )
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    REMEMBER_COOKIE_DURATION = 30 * 24 * 60 * 60  # 30 days


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
