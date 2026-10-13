"""Idempotent SQLite upgrade for the employee profile table."""
from sqlalchemy import inspect


def migrate_employee_table(engine):
    tables = inspect(engine).get_table_names()
    if 'pharmacist_profiles' not in tables and 'employee_table' not in tables:
        return
    if engine.dialect.name == 'postgresql':
        if 'pharmacist_profiles' in tables:
            raise RuntimeError('Legacy PostgreSQL profiles require an explicit migration')
        from app.models import Employee
        columns = {c['name'] for c in inspect(engine).get_columns('employee_table')}
        if not set(Employee.__table__.columns.keys()).issubset(columns):
            raise RuntimeError('PostgreSQL employee schema requires an explicit migration')
        return
    if engine.dialect.name != 'sqlite':
        raise RuntimeError('Unsupported database')
    if 'pharmacist_profiles' in tables and 'employee_table' in tables:
        raise RuntimeError('Both profile tables exist; reconcile them before upgrading')
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            if 'pharmacist_profiles' in inspect(connection).get_table_names():
                # SQLite updates the auth_sessions foreign key when renaming the table.
                connection.exec_driver_sql('ALTER TABLE pharmacist_profiles RENAME TO employee_table')
            columns = {column['name'] for column in inspect(connection).get_columns('employee_table')}
            additions = {
                'role': "VARCHAR(30) NOT NULL DEFAULT 'pharmacist' CHECK (role IN ('doctor','superadmin','admin','pharmacist','nurse','receptionist'))",
                'professional_bio': 'TEXT',
                'photo_data_url': 'TEXT',
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.exec_driver_sql(f'ALTER TABLE employee_table ADD COLUMN {name} {definition}')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
