"""
Aplicação Principal - Agenda Escolar
Ponto de entrada do sistema (Fábrica da aplicação, registro de Blueprints e CLI).
"""
import os
from flask import Flask, jsonify, url_for as flask_url_for
from models import db, Teacher
from extensions import init_extensions, celery, migrate, login_manager, csrf
from routes import auth_bp, agenda_bp, admin_bp, integrations_bp
from utils import clean_old_backups

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma-chave-secreta-muito-dificil-de-adivinhar')

# --- CONFIGURAÇÃO DE DIRETÓRIOS E BANCO DE DADOS ---
DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
BACKUP_FOLDER = os.path.join(DATA_DIR, 'backups')
os.makedirs(BACKUP_FOLDER, exist_ok=True)

database_uri = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(DATA_DIR, 'agenda.db'))
if database_uri.startswith("postgres://"):
    database_uri = database_uri.replace("postgres://", "postgresql+psycopg2://", 1)
elif database_uri.startswith("postgresql://"):
    database_uri = database_uri.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 # 50 MB

# --- INICIALIZAÇÃO DE EXTENSÕES E CELERY ---
init_extensions(app)

def ensure_schema_updates():
    """Garante de forma idempotente que novas colunas existam no banco sem necessidade de migration manual."""
    with app.app_context():
        try:
            engine = db.engine
            is_postgres = 'postgresql' in str(engine.url)
            if is_postgres:
                db.session.execute(db.text("ALTER TABLE booking ADD COLUMN IF NOT EXISTS classroom_or_notes VARCHAR(150);"))
            else:
                cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(booking);")).fetchall()]
                if cols and 'classroom_or_notes' not in cols:
                    db.session.execute(db.text("ALTER TABLE booking ADD COLUMN classroom_or_notes VARCHAR(150);"))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.warning(f"Aviso na verificação de schema: {e}")

ensure_schema_updates()

# --- REGISTRO DE BLUEPRINTS ---
app.register_blueprint(auth_bp)
app.register_blueprint(agenda_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(integrations_bp)
csrf.exempt(integrations_bp)


# --- ALIASES DE URL PARA COMPATIBILIDADE TOTAL ---
_endpoint_aliases = {
    'home': 'agenda.home',
    'select_shift': 'agenda.select_shift',
    'agenda_view': 'agenda.agenda_view',
    'book_slot': 'agenda.book_slot',
    'close_slot': 'agenda.close_slot',
    'delete_booking': 'agenda.delete_booking',
    'my_bookings': 'agenda.my_bookings',
    'delete_my_booking': 'agenda.delete_my_booking',
    'update_my_whatsapp': 'agenda.update_my_whatsapp',
    'login': 'auth.login',
    'logout': 'auth.logout',
    'admin_dashboard': 'admin.admin_dashboard',
    'add_resource': 'admin.add_resource',
    'edit_resource': 'admin.edit_resource',
    'delete_resource': 'admin.delete_resource',
    'copy_resource': 'admin.copy_resource',
    'reorder_resources': 'admin.reorder_resources',
    'toggle_resource': 'admin.toggle_resource',
    'manage_teachers': 'admin.manage_teachers',
    'edit_teacher': 'admin.edit_teacher',
    'toggle_teacher': 'admin.toggle_teacher',
    'delete_teacher': 'admin.delete_teacher',

    'manage_schedules': 'admin.manage_schedules',
    'reports': 'admin.reports',
    'export_report': 'admin.export_report',
    'weekly_view': 'admin.weekly_view',
    'backup_restore_page': 'admin.backup_restore_page',
    'backup_database': 'admin.backup_database',
    'restore_database': 'admin.restore_database',
    'change_password': 'admin.change_password',
}

def handle_build_error(error, endpoint, values):
    """Resolve automaticamente nomes de endpoints legados para seus equivalentes em Blueprints."""
    alias = _endpoint_aliases.get(endpoint)
    if alias:
        return flask_url_for(alias, **values)
    return None

app.url_build_error_handlers.append(handle_build_error)

# --- ENDPOINT DE MONITORAMENTO (HEALTHCHECK) ---
@app.route('/health')
def health_check():
    """Endpoint de verificação de integridade da aplicação e conectividade com o banco."""
    db_status = "connected"
    try:
        db.session.execute(db.text('SELECT 1'))
    except Exception as e:
        return jsonify({"status": "unhealthy", "database": f"error: {str(e)}"}), 500
    return jsonify({"status": "healthy", "database": db_status}), 200

# --- COMANDOS CLI ---
@app.cli.command("seed-db")
def seed_db_command():
    """Cria o usuário administrador padrão se ele não existir."""
    if not Teacher.query.filter_by(registration='7363').first():
        admin_user = Teacher(
            name='Jardel',
            registration='7363',
            is_admin=True
        )
        db.session.add(admin_user)
        db.session.commit()
        print('Usuário administrador padrão (Jardel) criado com sucesso.')
    else:
        print('Usuário administrador padrão (Jardel) já existe.')

@app.cli.command("clean-backups")
def clean_backups_command():
    """Remove backups antigos da pasta de dados respeitando a política de retenção."""
    deleted = clean_old_backups(BACKUP_FOLDER, keep_latest=10, max_days=14)
    print(f'{len(deleted)} backup(s) antigo(s) removido(s).')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')