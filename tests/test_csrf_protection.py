"""
Testes automatizados de segurança e proteção CSRF (Cross-Site Request Forgery).
"""
import re
import unittest
from app import app
from models import db, Teacher

class CSRFProtectionTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = True  # Habilita CSRF expressamente para o teste
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Garante a existência do professor de teste
        self.teacher = Teacher.query.filter_by(registration='7363').first()
        if not self.teacher:
            self.teacher = Teacher(name='Jardel Admin', registration='7363', is_admin=True)
            db.session.add(self.teacher)
            db.session.commit()

    def tearDown(self):
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context.pop()

    def test_post_without_csrf_token_rejected_with_400(self):
        """Valida que qualquer requisição POST sem token CSRF é rejeitada com HTTP 400."""
        res = self.client.post('/login', data={'registration': '7363'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('CSRF', res.get_data(as_text=True))

    def test_post_with_valid_csrf_token_accepted(self):
        """Valida que uma requisição POST acompanhada de token CSRF válido é processada com sucesso."""
        # 1. Carrega a página para obter o cookie de sessão e o token do formulário
        get_res = self.client.get('/login')
        self.assertEqual(get_res.status_code, 200)

        # Extrai o valor do token CSRF do HTML
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_res.get_data(as_text=True))
        self.assertIsNotNone(match, "Token CSRF não encontrado no formulário de login")
        csrf_token = match.group(1)

        # 2. Submete o formulário com o token CSRF válido
        post_res = self.client.post('/login', data={
            'registration': '7363',
            'csrf_token': csrf_token
        })
        # Login bem-sucedido redireciona (302) para a home
        self.assertEqual(post_res.status_code, 302)
        self.assertIn('/', post_res.headers.get('Location', ''))

if __name__ == '__main__':
    unittest.main()
