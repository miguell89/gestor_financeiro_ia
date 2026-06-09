import json
import random
import string
from datetime import datetime, timedelta

from app.database import db
from app.services.log_service import create_log

LINK_CODE_TTL_HOURS = 24
UNLINKED_TELEGRAM_MESSAGE = "Seu Telegram ainda nao esta vinculado. Solicite ao administrador a geracao de um codigo de vinculacao."


def _utc_now():
    return datetime.utcnow().replace(microsecond=0)


def _iso(value):
    return value.isoformat(sep=" ")


def _parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("T", " ")).replace(tzinfo=None)


def ensure_telegram_link_schema(conn):
    user_columns = [row["name"] for row in conn.execute("pragma table_info(users)").fetchall()]
    if "telegram_username" not in user_columns:
        conn.execute("alter table users add column telegram_username text")
    if "telegram_first_name" not in user_columns:
        conn.execute("alter table users add column telegram_first_name text")
    user_migrations = {
        "telegram_status": "alter table users add column telegram_status text not null default 'nao_conectado'",
        "telegram_link_code": "alter table users add column telegram_link_code text",
        "telegram_link_code_expires_at": "alter table users add column telegram_link_code_expires_at text",
        "telegram_linked_at": "alter table users add column telegram_linked_at text",
        "telegram_last_interaction": "alter table users add column telegram_last_interaction text",
        "receive_telegram_alerts": "alter table users add column receive_telegram_alerts integer not null default 0",
        "receive_telegram_reports": "alter table users add column receive_telegram_reports integer not null default 0",
        "receive_telegram_bill_reminders": "alter table users add column receive_telegram_bill_reminders integer not null default 0",
        "receive_telegram_ai_analysis": "alter table users add column receive_telegram_ai_analysis integer not null default 0",
    }
    user_columns = [row["name"] for row in conn.execute("pragma table_info(users)").fetchall()]
    for column, sql in user_migrations.items():
        if column not in user_columns:
            conn.execute(sql)
    conn.execute("update users set telegram_status = 'conectado' where telegram_id is not null and (telegram_status is null or telegram_status = '' or telegram_status = 'nao_conectado')")
    conn.execute("update users set telegram_status = 'nao_conectado' where telegram_id is null and (telegram_status is null or telegram_status = '')")
    conn.execute(
        """
        create table if not exists telegram_link_codes (
          id integer primary key autoincrement,
          user_id integer not null,
          code text not null unique,
          expires_at text not null,
          used_at text,
          created_at text default current_timestamp,
          foreign key (user_id) references users(id)
        )
        """
    )


def _new_code():
    alphabet = string.ascii_uppercase + string.digits
    return "GFI-" + "".join(random.choice(alphabet) for _ in range(6))


def _create_log_with_conn(conn, level, action, message="", user_id=None, telegram_id=None, details=None):
    conn.execute(
        """
        insert into system_logs (level, source, user_id, telegram_id, action, message, details_json)
        values (?, 'telegram', ?, ?, ?, ?, ?)
        """,
        (level, user_id, telegram_id, action, message, json.dumps(details or {}, ensure_ascii=False)),
    )


def generate_link_code(user_id):
    expires_at = _utc_now() + timedelta(hours=LINK_CODE_TTL_HOURS)
    with db() as conn:
        ensure_telegram_link_schema(conn)
        conn.execute("update telegram_link_codes set used_at = current_timestamp where user_id = ? and used_at is null", (user_id,))
        for _ in range(20):
            code = _new_code()
            existing = conn.execute("select id from users where telegram_link_code = ?", (code,)).fetchone()
            if existing:
                continue
            conn.execute(
                """
                update users
                set telegram_link_code = ?,
                    telegram_link_code_expires_at = ?,
                    telegram_status = 'pendente'
                where id = ?
                """,
                (code, _iso(expires_at), user_id),
            )
            try:
                conn.execute("insert into telegram_link_codes (user_id, code, expires_at) values (?, ?, ?)", (user_id, code, _iso(expires_at)))
            except Exception:
                pass
            return {"code": code, "expires_at": _iso(expires_at)}
    raise ValueError("Nao foi possivel gerar um codigo agora.")


def get_user_telegram_status(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        user = conn.execute(
            """
            select id, telegram_id, telegram_username, telegram_first_name, telegram_status,
                   telegram_link_code, telegram_link_code_expires_at, telegram_linked_at,
                   telegram_last_interaction, last_interaction_at
            from users
            where id = ?
            """,
            (user_id,),
        ).fetchone()
    active_code = None
    if user and user["telegram_link_code"] and _parse_datetime(user["telegram_link_code_expires_at"]) and _parse_datetime(user["telegram_link_code_expires_at"]) > _utc_now():
        active_code = {"code": user["telegram_link_code"], "expires_at": user["telegram_link_code_expires_at"]}
    return {"user": dict(user) if user else None, "active_code": active_code, "ttl_hours": LINK_CODE_TTL_HOURS}


def resolve_telegram_user(telegram_id):
    if not telegram_id:
        return None
    with db() as conn:
        ensure_telegram_link_schema(conn)
        user = conn.execute(
            """
            select *
            from users
            where telegram_id = ? and status = 'ativo' and telegram_status = 'conectado'
            """,
            (str(telegram_id),),
        ).fetchone()
        if user:
            conn.execute("update users set last_interaction_at = current_timestamp, telegram_last_interaction = current_timestamp where id = ?", (user["id"],))
            return user["id"]
    return None


def link_telegram_account(code, telegram_user):
    clean_code = (code or "").strip().upper()
    if not clean_code:
        raise ValueError("Envie assim: /vincular SEU_CODIGO")

    telegram_id = str(telegram_user.id)
    username = getattr(telegram_user, "username", None)
    first_name = getattr(telegram_user, "first_name", None)
    now = _utc_now()
    create_log(
        "info",
        "telegram",
        "link_command_received",
        "Comando /vincular recebido",
        telegram_id=telegram_id,
        details={"code": clean_code, "telegram_username": username, "telegram_first_name": first_name},
    )

    with db() as conn:
        ensure_telegram_link_schema(conn)
        user = conn.execute(
            """
            select *
            from users
            where telegram_link_code = ? and telegram_status = 'pendente'
            """,
            (clean_code,),
        ).fetchone()
        if not user:
            _create_log_with_conn(conn, "warning", "link_code_not_found", "Codigo invalido ou nao pendente", telegram_id=telegram_id, details={"code": clean_code})
            raise ValueError("❌ Código inválido ou expirado. Gere um novo código no sistema.")
        if not user["telegram_link_code_expires_at"] or _parse_datetime(user["telegram_link_code_expires_at"]) <= now:
            _create_log_with_conn(conn, "warning", "link_code_expired", "Codigo Telegram expirado", user_id=user["id"], telegram_id=telegram_id, details={"code": clean_code, "expires_at": user["telegram_link_code_expires_at"]})
            raise ValueError("❌ Código inválido ou expirado. Gere um novo código no sistema.")
        _create_log_with_conn(conn, "info", "link_user_found", "Usuario encontrado pelo codigo Telegram", user_id=user["id"], telegram_id=telegram_id, details={"code": clean_code})

        existing = conn.execute(
            "select id from users where telegram_id = ? and id != ?",
            (telegram_id, user["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """
                update users
                set telegram_id = null,
                    telegram_username = null,
                    telegram_first_name = null,
                    telegram_status = 'nao_conectado',
                    telegram_linked_at = null
                where id = ?
                """,
                (existing["id"],),
            )

        conn.execute(
            """
            update users
            set telegram_id = ?,
                telegram_username = ?,
                telegram_first_name = ?,
                telegram_status = 'conectado',
                telegram_link_code = null,
                telegram_link_code_expires_at = null,
                telegram_linked_at = current_timestamp,
                telegram_last_interaction = current_timestamp,
                last_interaction_at = current_timestamp
            where id = ?
            """,
            (telegram_id, username, first_name, user["id"]),
        )
        conn.execute("update telegram_link_codes set used_at = current_timestamp where code = ?", (clean_code,))
        linked_user = conn.execute("select name from users where id = ?", (user["id"],)).fetchone()
        _create_log_with_conn(conn, "info", "link_update_success", "Telegram vinculado no banco", user_id=user["id"], telegram_id=telegram_id, details={"code": clean_code, "telegram_username": username})
    return {"user_id": user["id"], "name": linked_user["name"] if linked_user else ""}


def unlink_telegram_account(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        conn.execute(
            """
            update users
            set telegram_id = null,
                telegram_username = null,
                telegram_first_name = null,
                telegram_status = 'nao_conectado',
                telegram_link_code = null,
                telegram_link_code_expires_at = null,
                telegram_linked_at = null
            where id = ?
            """,
            (user_id,),
        )
        conn.execute("update telegram_link_codes set used_at = current_timestamp where user_id = ? and used_at is null", (user_id,))
    return True
