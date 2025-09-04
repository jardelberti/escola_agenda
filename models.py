from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Inicializa o objeto do banco de dados
db = SQLAlchemy()

# Tabela de Usuário (Admin)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Tabela de Recursos (Salas/Equipamentos)
class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    # CAMPO DE ÍCONE ADICIONADO
    icon = db.Column(db.String(50), nullable=True, default='bi-box')

# Tabela para Estrutura de Horário
class ScheduleTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift = db.Column(db.String(50), unique=True, nullable=False)  # "matutino" ou "vespertino"
    slots = db.Column(db.JSON, nullable=False)

# Tabela para Agendamentos
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    slot_name = db.Column(db.String(100), nullable=False)
    teacher_name = db.Column(db.String(100))
    status = db.Column(db.String(50), nullable=False, default='booked') # 'booked' ou 'closed'
