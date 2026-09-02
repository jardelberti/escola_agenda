"""
Testes automatizados para saúde da aplicação, retenção de backups e validação de arquivos.
"""
import os
import time
import tempfile
import unittest
from io import BytesIO
from app import app, clean_old_backups
from models import db, Teacher

class BackupAndHealthTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Garante a existência do admin para os testes autenticados
        self.admin = Teacher.query.filter_by(registration='7363').first()
        if not self.admin:
            self.admin = Teacher(name='Jardel Admin', registration='7363', is_admin=True)
            db.session.add(self.admin)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_health_endpoint(self):
        """Valida que o endpoint /health retorna status 200 e banco conectado."""
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')

    def test_clean_old_backups_retention(self):
        """Valida que a função clean_old_backups preserva a cota mínima e limpa arquivos antigos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria 15 arquivos de backup fictícios com datas diferentes
            now = time.time()
            for i in range(15):
                fpath = os.path.join(tmpdir, f'backup_postgres_202601{i:02d}.sql')
                with open(fpath, 'w') as f:
                    f.write('dummy content')
                # 5 arquivos recentes (1 dia atrás) e 10 antigos (30 dias atrás)
                if i < 5:
                    mtime = now - (86400 * 1) # 1 dia
                else:
                    mtime = now - (86400 * 30) # 30 dias
                os.utime(fpath, (mtime, mtime))

            # Executa com keep_latest=10 e max_days=14
            deleted = clean_old_backups(folder=tmpdir, keep_latest=10, max_days=14)

            # Os 10 mais recentes devem ser mantidos. Os 5 restantes têm mais de 14 dias, logo devem ser deletados.
            self.assertEqual(len(deleted), 5)
            remaining_files = os.listdir(tmpdir)
            self.assertEqual(len(remaining_files), 10)

    def test_restore_rejects_invalid_file_extension(self):
        """Valida que /admin/restore rejeita extensões não autorizadas (ex: .exe, .txt)."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        fake_file = (BytesIO(b'malicious content'), 'exploit.exe')
        res = self.client.post('/admin/restore', data={
            'backup_file': fake_file
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn('Extensão de arquivo não permitida', res.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
