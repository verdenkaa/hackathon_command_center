from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text


def test_upgrade_preserves_previews_and_account_data(tmp_path,monkeypatch):
    from app.config import settings
    backend=Path(__file__).resolve().parents[1]
    url=f"sqlite:///{(tmp_path/'telegram-migration.db').as_posix()}"
    monkeypatch.setattr(settings,'database_url',url)
    cfg=Config(str(backend/'alembic.ini'))
    cfg.set_main_option('script_location',str(backend/'alembic'))
    command.upgrade(cfg,'20261028_advisor')
    engine=create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (login,password_hash,display_name,active,created_at) VALUES ('keep','hash','Keep',1,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO telegram_deliveries (event_type,text,mentions,mode,created_at) VALUES ('task_assigned','Keep old preview','[]','mock',CURRENT_TIMESTAMP)"))
    command.upgrade(cfg,'head')
    with engine.connect() as db:
        assert db.execute(text('SELECT text,state,chat_id,message_ids FROM telegram_deliveries')).one()==('Keep old preview','preview',None,'[]')
        assert db.execute(text('SELECT login,password_hash,display_name,active,deleted_identity FROM users')).one()==('keep','hash','Keep',1,0)
        assert not db.execute(text('PRAGMA foreign_key_check')).all()
    engine.dispose()
