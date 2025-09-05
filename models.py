from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

# Inicializa o objeto do banco de dados
db = SQLAlchemy()

# A tabela Teacher foi simplificada, removendo os campos de senha
class Teacher(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    registration = db.Column(db.String(50), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

# Tabela de Recursos (Salas/Equipamentos)
class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    icon = db.Column(db.String(50))

# Tabela para Estrutura de Horário (ligada ao Recurso)
class ScheduleTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    shift = db.Column(db.String(50), nullable=False)  # "matutino" ou "vespertino"
    slots = db.Column(db.JSON, nullable=False)
    # Garante que um recurso só pode ter um template por turno
    __table_args__ = (db.UniqueConstraint('resource_id', 'shift', name='_resource_shift_uc'),)

# Tabela para Agendamentos
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    teacher_name = db.Column(db.String(150), nullable=False)
    date = db.Column(db.Date, nullable=False)
    slot_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='booked') # 'booked' ou 'closed'

