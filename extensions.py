"""
Inicialização e configuração centralizada de extensões do Flask.
"""
import os
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from celery import Celery
from models import db, Teacher

migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
celery = Celery(__name__)

login_manager.login_view = 'auth.login'
login_manager.login_message = "Você precisa fazer login para acessar esta página."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Teacher, int(user_id))

def init_extensions(app):
    """Inicializa todas as extensões vinculando-as à aplicação Flask."""
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    # Configuração do Celery
    app.config.setdefault('CELERY_BROKER_URL', os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'))
    app.config.setdefault('CELERY_RESULT_BACKEND', os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'))

    celery.conf.update(
        broker_url=app.config['CELERY_BROKER_URL'],
        result_backend=app.config['CELERY_RESULT_BACKEND']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
