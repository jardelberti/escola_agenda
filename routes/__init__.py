"""
Pacote de rotas modularizadas da Agenda Escolar.
"""
from routes.auth import auth_bp
from routes.agenda import agenda_bp
from routes.admin import admin_bp
from routes.integrations import integrations_bp

__all__ = ['auth_bp', 'agenda_bp', 'admin_bp', 'integrations_bp']

