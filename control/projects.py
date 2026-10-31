"""Copy a legacy project without modifying its source database."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from control.archives import ArchiveError


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def split_database(source: Path, target: Path, project_id: int) -> None:
    if target.exists():
        raise ArchiveError('Целевая база уже существует')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(target)) as db:
            original.backup(db)
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            if not db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                raise ArchiveError('Проект не найден')
            # Sessions, host security policy, archives and unscoped operational logs
            # belong to the old installation and must never cross this boundary.
            for table in ('sessions', 'login_events', 'ip_rules', 'backup_records', 'sandbox_runs', 'advisor_attempts'):
                if table in tables:
                    db.execute(f'DELETE FROM {quote(table)}')
            for table in tables:
                columns = {r[1] for r in db.execute(f'PRAGMA table_info({quote(table)})')}
                if 'project_id' in columns:
                    db.execute(f'DELETE FROM {quote(table)} WHERE project_id IS NOT NULL AND project_id != ?', (project_id,))
                    if table != 'role_assignments':
                        db.execute(f'DELETE FROM {quote(table)} WHERE project_id IS NULL')
            db.execute('DELETE FROM projects WHERE id != ?', (project_id,))
            # Remove children of discarded project rows, transitively.
            while True:
                changed = 0
                for table in tables:
                    for fk in db.execute(f'PRAGMA foreign_key_list({quote(table)})').fetchall():
                        parent, column, key = fk[2:5]
                        if parent == 'users':
                            continue
                        changed += db.execute(f'DELETE FROM {quote(table)} WHERE {quote(column)} IS NOT NULL AND {quote(column)} NOT IN (SELECT {quote(key)} FROM {quote(parent)})').rowcount
                if not changed:
                    break
            # Keep members/admins and historical actors needed by retained records.
            references: list[str] = ['SELECT user_id FROM role_assignments']
            for table in tables:
                if table == 'users':
                    continue
                for fk in db.execute(f'PRAGMA foreign_key_list({quote(table)})'):
                    if fk[2] == 'users':
                        references.append(f'SELECT {quote(fk[3])} FROM {quote(table)} WHERE {quote(fk[3])} IS NOT NULL')
            db.execute('DELETE FROM users WHERE id NOT IN (' + ' UNION '.join(references) + ')')
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ArchiveError('Не удалось сохранить целостность проекта; исходник сохранён')
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ArchiveError('Копия проекта не прошла проверку')
