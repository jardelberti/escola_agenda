"""Run before restarting code that selects new fields. Never imports app."""
import os
import sys
import argparse
from pathlib import Path
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth_schema import upgrade_admin_auth, secure_restored_admin_accounts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after-restore', action='store_true', help='Também revoga sessões e links após uma restauração manual.')
    args = parser.parse_args()
    uri = os.environ.get('DATABASE_URL', 'sqlite:///' + str(ROOT / 'data' / 'agenda.db'))
    if uri.startswith('postgres://'):
        uri = uri.replace('postgres://', 'postgresql+psycopg2://', 1)
    engine = create_engine(uri)
    with engine.begin() as connection:
        if args.after_restore:
            secure_restored_admin_accounts(connection)
        else:
            upgrade_admin_auth(connection)
    engine.dispose()
    print('Schema da proteção administrativa atualizado (sem excluir dados).')
