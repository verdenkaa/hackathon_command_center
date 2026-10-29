from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import update

from app.api.errors import api_error
from app.db.models import TelegramSettings, TelegramDelivery, User
from app.deps import get_db, require_admin, require_captain_or_admin, project_member_ids
from app.services import telegram as svc, telegram_vault as vault
from app.services.audit import write_audit
from app.telegram_schemas import TelegramConfig, TestDelivery, DeliveryRetry
from app.timeutil import utcnow

router = APIRouter(tags=['telegram'])


@router.get('/telegram/bot')
def bot(_user: User = Depends(require_admin)) -> dict:
    return {'connected': vault.is_saved(), 'vault_available': vault.available()}


@router.delete('/telegram/bot/key')
def delete_key(db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict:
    try:
        vault.delete()
    except (vault.VaultUnavailable, OSError):
        raise api_error(409, 'VAULT_UNAVAILABLE', 'Хранилище Windows недоступно') from None
    write_audit(db, action='telegram.key_removed', actor_id=user.id)
    db.commit()
    return {'connected': False}


@router.get('/projects/{project_id}/telegram')
def settings(project_id: int, db: Session = Depends(get_db), _user: User = Depends(require_captain_or_admin)) -> dict:
    cfg = db.get(TelegramSettings, project_id)
    users = db.query(User).filter(User.id.in_(project_member_ids(db, project_id))).all()
    return {'project_id': project_id, 'bot_connected': vault.is_saved(),
            'chat_id': cfg.chat_id if cfg else None, 'routes': cfg.routes if cfg else {},
            'public_url': cfg.public_url if cfg else '', 'events': svc.EVENTS,
            'missing_usernames': [{'id': u.id, 'name': u.display_name} for u in users
                                  if svc.mentions(db, [u.id])[1]],
            'pending': db.query(TelegramDelivery).filter(TelegramDelivery.project_id == project_id,
                       TelegramDelivery.state.in_(('pending', 'sending'))).count(),
            'queue_policy': 'Ожидающие сообщения сохраняют исходный чат и тему. Смена настроек влияет только на новые события.'}


@router.put('/projects/{project_id}/telegram')
def save(project_id: int, body: TelegramConfig, db: Session = Depends(get_db),
         user: User = Depends(require_captain_or_admin)) -> dict:
    cfg = db.get(TelegramSettings, project_id)
    old_chat = cfg.chat_id if cfg else None
    if old_chat != body.chat_id and not body.confirm_chat:
        raise api_error(409, 'CHAT_CONFIRMATION_REQUIRED', 'Подтвердите чат текущего проекта; старая очередь сохранит прежнее направление')
    if cfg is None:
        cfg = TelegramSettings(project_id=project_id)
        db.add(cfg)
    cfg.chat_id, cfg.routes, cfg.public_url = body.chat_id, body.routes, body.public_url
    write_audit(db, action='telegram.configured', actor_id=user.id, project_id=project_id,
                data={'chat_id': body.chat_id, 'routes': body.routes})
    db.commit()
    return settings(project_id, db, user)


@router.post('/projects/{project_id}/telegram/test', status_code=202)
def test(project_id: int, body: TestDelivery, db: Session = Depends(get_db),
         user: User = Depends(require_captain_or_admin)) -> dict:
    cfg = db.get(TelegramSettings, project_id)
    if not cfg or not cfg.chat_id or cfg.chat_id != body.confirmed_chat_id:
        raise api_error(409, 'CHAT_MISMATCH', 'Сначала сохраните и подтвердите тестовый чат текущего проекта')
    row = svc.enqueue(db, project_id, 'test', f'🧪 ТЕСТОВОЕ сообщение платформы\n\nПроект: #{project_id}\nПроверка доставки Telegram.', [], test_thread=body.thread_id)
    write_audit(db, action='telegram.test_queued', actor_id=user.id, project_id=project_id)
    db.commit()
    return {'id': row.id, 'state': row.state}


@router.get('/projects/{project_id}/telegram/deliveries')
def deliveries(project_id: int, db: Session = Depends(get_db), _user: User = Depends(require_captain_or_admin)) -> list[dict]:
    return [{'id': row.id, 'event_type': row.event_type, 'chat_id': row.chat_id,
             'thread_id': row.thread_id, 'state': row.state, 'attempts': row.attempts,
             'error': svc.ERRORS.get(row.error_code), 'created_at': row.created_at,
             'attempted_at': row.attempted_at, 'next_attempt_at': row.next_attempt_at,
             'sent_at': row.sent_at, 'parts_sent': len(row.message_ids)}
            for row in db.query(TelegramDelivery).filter_by(project_id=project_id, mode='live')
            .order_by(TelegramDelivery.id.desc()).limit(50)]


@router.post('/projects/{project_id}/telegram/deliveries/{delivery_id}/retry')
def retry(project_id: int, delivery_id: int, body: DeliveryRetry, db: Session = Depends(get_db),
          user: User = Depends(require_captain_or_admin)) -> dict:
    row = db.query(TelegramDelivery).filter_by(id=delivery_id, project_id=project_id, mode='live').first()
    if row is None:
        raise api_error(404, 'NOT_FOUND', 'Доставка не найдена')
    if row.state not in ('error', 'uncertain'):
        raise api_error(409, 'INVALID_STATE', 'Повтор доступен только для ошибок доставки')
    if row.state == 'uncertain' and not body.accept_duplicate_risk:
        raise api_error(409, 'DUPLICATE_RISK', 'Сообщение могло быть отправлено. Подтвердите риск дубля')
    values = {'state':'pending', 'next_attempt_at':utcnow(), 'attempts':0, 'error_code':None}
    if row.error_code == 'CONTENT_CHANGED':
        values['message_ids'] = []
    claimed = db.execute(update(TelegramDelivery).where(TelegramDelivery.id == row.id,
        TelegramDelivery.state == row.state).values(**values))
    if claimed.rowcount != 1:
        raise api_error(409, 'INVALID_STATE', 'Состояние доставки изменилось. Обновите историю')
    write_audit(db, action='telegram.retry', actor_id=user.id, project_id=project_id,
                entity_type='telegram_delivery', entity_id=row.id, data={'duplicate_risk_accepted': body.accept_duplicate_risk})
    db.commit()
    return {'id': row.id, 'state': row.state}
