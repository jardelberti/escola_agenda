from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import time
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

# Inicializa o objeto do banco de dados
db = SQLAlchemy()

# Senha obrigatória apenas para contas administrativas.
class Teacher(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    registration = db.Column(db.String(50), unique=True, nullable=False)
    whatsapp = db.Column(db.String(30), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    password_hash = db.Column(db.String(255), nullable=True)
    auth_version = db.Column(db.String(64), nullable=True)

    def get_id(self):
        if self.is_admin:
            # Server-checked expiry also limits a copied remember cookie.
            return f'{self.id}:{self.auth_version}:{int(time.time()) + 7 * 86400}'
        return str(self.id)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='scrypt')
        self.auth_version = secrets.token_hex(32)

    def check_password(self, password):
        return bool(self.password_hash and check_password_hash(self.password_hash, password))


class AdminAccessToken(db.Model):
    token_hash = db.Column(db.String(64), primary_key=True)
    # No FK: an old pg_dump must remain able to recreate teacher. Resolution is
    # checked at consumption; deletion/role changes explicitly remove the tokens.
    teacher_id = db.Column(db.Integer, nullable=False, index=True)
    expires_at = db.Column(db.BigInteger, nullable=False)


class AuthAttempt(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    window_start = db.Column(db.BigInteger, nullable=False)
    attempts = db.Column(db.Integer, nullable=False)



# Tabela de Recursos (Salas/Equipamentos)
class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    icon = db.Column(db.String(50))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    max_weekly_bookings = db.Column(db.Integer, nullable=True, default=None) # Limite semanal por professor (None = ilimitado)
    
    # CORREÇÃO: Adiciona o relacionamento para encontrar os templates de horário
    schedule_templates = db.relationship('ScheduleTemplate', backref='resource', lazy=True, cascade='all, delete-orphan')

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
    shift = db.Column(db.String(50), nullable=False)
    slot_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='booked') # 'booked' ou 'closed'
    classroom_or_notes = db.Column(db.String(150), nullable=True) # Ex: Turma 7º B ou Finalidade
    created_at = db.Column(db.DateTime, default=db.func.now(), server_default=db.func.now())

    resource = db.relationship('Resource', backref=db.backref('bookings', lazy=True))

    # Garante integridade de agendamentos e impede reserva duplicada pelo mesmo professor no mesmo horário
    __table_args__ = (
        db.Index(
            'uq_booking_teacher_active',
            'resource_id', 'teacher_id', 'date', 'shift', 'slot_name',
            unique=True,
            postgresql_where=db.text("status = 'booked'"),
            sqlite_where=db.text("status = 'booked'")
        ),
        db.Index('idx_booking_resource_date', 'resource_id', 'date'),
        db.Index('idx_booking_teacher_date', 'teacher_id', 'date'),
    )

# Tabela de Auditoria de Cancelamentos
class BookingAuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, nullable=True)
    resource_name = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    shift = db.Column(db.String(50), nullable=False)
    slot_name = db.Column(db.String(100), nullable=False)
    teacher_name = db.Column(db.String(150), nullable=False)
    classroom_or_notes = db.Column(db.String(150), nullable=True)
    action = db.Column(db.String(50), nullable=False, default='cancelado')
    performed_by_name = db.Column(db.String(150), nullable=False)
    performed_by_is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)

