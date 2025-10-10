from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


usuario_disciplina = db.Table('usuario_disciplina',
                              db.Column('usuario_id', db.Integer, db.ForeignKey(
                                  'usuario.id'), primary_key=True),
                              db.Column('disciplina_id', db.Integer, db.ForeignKey(
                                  'disciplina.id'), primary_key=True)
                              )


class Escola(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False, unique=True)
    nome_diretor = db.Column(db.String(150))
    email_contato = db.Column(db.String(150))
    telefone_fixo = db.Column(db.String(20))
    telefone_celular = db.Column(db.String(20))
    cep = db.Column(db.String(10))
    endereco = db.Column(db.String(255))
    numero = db.Column(db.String(20))
    bairro = db.Column(db.String(100))
    cidade = db.Column(db.String(100))
    estado = db.Column(db.String(50))
    pais = db.Column(db.String(100), default='Brasil')
    status = db.Column(db.String(50), nullable=False, default='ativo')
    logo_url = db.Column(db.String(255))
    recursos = db.relationship(
        'Resource', backref='escola', lazy=True, cascade='all, delete-orphan')
    assinaturas = db.relationship(
        'Assinatura', backref='escola', lazy=True, cascade='all, delete-orphan')
    disciplinas = db.relationship(
        'Disciplina', backref='escola', lazy=True, cascade='all, delete-orphan')


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    nome_curto = db.Column(db.String(50))
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    is_superadmin = db.Column(db.Boolean, default=False)
    email_confirmado = db.Column(db.Boolean, nullable=False, default=False)
    foto_perfil = db.Column(db.String(255))

    escolas = db.relationship(
        'UsuarioEscola', backref='usuario', lazy='dynamic', cascade='all, delete-orphan')
    disciplinas = db.relationship('Disciplina', secondary=usuario_disciplina, lazy='subquery',
                                  backref=db.backref('usuarios', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # --- CORREÇÃO IMPORTANTE AQUI ---
        # Se não houver hash de senha (ex: conta social), retorna sempre False.
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        if self.is_superadmin:
            return True
        return any(assoc.papel == 'admin' for assoc in self.escolas)

# 3. Nova tabela de associação (muitos-para-muitos)
#    Liga Usuarios a Escolas e define o papel de cada um


class Disciplina(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    escola_id = db.Column(db.Integer, db.ForeignKey(
        'escola.id'), nullable=False)


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
    escola_id = db.Column(db.Integer, db.ForeignKey(
        'escola.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    icon = db.Column(db.String(50))
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    # Define o número mínimo de dias de antecedência para agendar.
    # O server_default='0' instrui o banco de dados a preencher
    # as linhas existentes com o valor 0 durante a migração.
    min_agendamento_dias = db.Column(
        db.Integer, nullable=False, default=0, server_default='0')

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
