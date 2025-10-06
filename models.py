from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# --- NOVOS MODELOS E MODELOS ATUALIZADOS ---

# 1. Nova tabela para gerenciar as escolas (tenants)


class Escola(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False, unique=True)
    # Status pode ser 'ativo', 'inativo', 'aguardando_pagamento'
    status = db.Column(db.String(50), nullable=False, default='ativo')
    # Futuramente, para gerenciar assinaturas
    # plano_id = db.Column(db.Integer, db.ForeignKey('plano.id'))
    logo_url = db.Column(db.String(255))  # Para a logo de cada escola

    # Relacionamentos
    recursos = db.relationship(
        'Resource', backref='escola', lazy=True, cascade='all, delete-orphan')
    assinaturas = db.relationship(
        'Assinatura', backref='escola', lazy=True, cascade='all, delete-orphan')

# 2. Tabela 'Teacher' renomeada para 'Usuario' e modernizada


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    is_superadmin = db.Column(db.Boolean, default=False)
    email_confirmado = db.Column(db.Boolean, nullable=False, default=False)

    escolas = db.relationship(
        'UsuarioEscola', backref='usuario', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- ADICIONE ESTE CÓDIGO ---
    @property
    def is_admin(self):
        """Verifica se este usuário tem o papel de 'admin' em QUALQUER escola associada."""
        if self.is_superadmin:
            return True
        return any(assoc.papel == 'admin' for assoc in self.escolas)
    # --- FIM DO CÓDIGO ADICIONADO ---

# 3. Nova tabela de associação (muitos-para-muitos)
#    Liga Usuarios a Escolas e define o papel de cada um


class UsuarioEscola(db.Model):
    usuario_id = db.Column(db.Integer, db.ForeignKey(
        'usuario.id'), primary_key=True)
    escola_id = db.Column(db.Integer, db.ForeignKey(
        'escola.id'), primary_key=True)

    # O papel do usuário DENTRO daquela escola
    papel = db.Column(db.String(50), nullable=False)  # 'admin' ou 'professor'

    # A matrícula agora vive aqui, pois pertence ao contexto de uma escola específica
    matricula = db.Column(db.String(50))

    escola = db.relationship('Escola', backref=db.backref(
        'membros', cascade='all, delete-orphan'))

# --- MODELOS EXISTENTES COM A ADIÇÃO DO 'escola_id' ---


class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Adiciona a chave estrangeira para ligar o recurso a uma escola
    escola_id = db.Column(db.Integer, db.ForeignKey(
        'escola.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    icon = db.Column(db.String(50))
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    schedule_templates = db.relationship(
        'ScheduleTemplate', backref='resource', lazy=True, cascade='all, delete-orphan')


class ScheduleTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey(
        'resource.id'), nullable=False)
    shift = db.Column(db.String(50), nullable=False)
    slots = db.Column(db.JSON, nullable=False)
    __table_args__ = (db.UniqueConstraint(
        'resource_id', 'shift', name='_resource_shift_uc'),)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Adiciona a chave estrangeira para ligar o agendamento a uma escola
    escola_id = db.Column(db.Integer, db.ForeignKey(
        'escola.id'), nullable=False)

    resource_id = db.Column(db.Integer, db.ForeignKey(
        'resource.id'), nullable=False)
    # Agora o agendamento é feito por um 'usuario_id'
    usuario_id = db.Column(db.Integer, db.ForeignKey(
        'usuario.id'), nullable=False)
    # Mantemos o nome para performance, mas a ligação real é com o usuario_id
    teacher_name = db.Column(db.String(150), nullable=False)
    date = db.Column(db.Date, nullable=False)
    shift = db.Column(db.String(50), nullable=False)
    slot_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='booked')

# 4. Nova tabela para os planos de assinatura disponíveis


class Plano(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True,
                     nullable=False)  # Ex: "Mensal", "Anual"
    # Preço em centavos para evitar problemas com ponto flutuante
    preco = db.Column(db.Integer, nullable=False)
    # Duração do plano em meses
    duracao_meses = db.Column(db.Integer, nullable=False)
    stripe_price_id = db.Column(db.String(100))

# 5. Nova tabela para registrar a assinatura de cada escola


class Assinatura(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    escola_id = db.Column(db.Integer, db.ForeignKey(
        'escola.id'), nullable=False)
    plano_id = db.Column(db.Integer, db.ForeignKey('plano.id'), nullable=False)
    data_inicio = db.Column(db.Date, nullable=False)
    data_fim = db.Column(db.Date, nullable=False)
    # Status pode ser 'ativa', 'vencida', 'cancelada'
    status = db.Column(db.String(50), nullable=False, default='ativa')

    # Relacionamentos para facilitar as consultas
    plano = db.relationship('Plano')
