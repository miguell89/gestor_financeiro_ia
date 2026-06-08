import random
from datetime import datetime, timedelta

from app.database import db

LINK_CODE_TTL_MINUTES = 15
UNLINKED_TELEGRAM_MESSAGE = "Seu Telegram ainda nao esta vinculado. Acesse o sistema web em Configuracoes > Telegram e gere um codigo de vinculacao."


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


def generate_link_code(user_id):
    expires_at = _utc_now() + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    with db() as conn:
        ensure_telegram_link_schema(conn)
        conn.execute("update telegram_link_codes set used_at = current_timestamp where user_id = ? and used_at is null", (user_id,))
        for _ in range(20):
            code = f"MGF-{random.randint(100000, 999999)}"
            try:
                conn.execute(
                    """
                    insert into telegram_link_codes (user_id, code, expires_at)
                    values (?, ?, ?)
                    """,
                    (user_id, code, _iso(expires_at)),
                )
                return {"code": code, "expires_at": _iso(expires_at)}
            except Exception:
                continue
    raise ValueError("Nao foi possivel gerar um codigo agora.")


def get_user_telegram_status(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        user = conn.execute(
            """
            select id, telegram_id, telegram_username, telegram_first_name, last_interaction_at
            from users
            where id = ?
            """,
            (user_id,),
        ).fetchone()
        code = conn.execute(
            """
            select code, expires_at, used_at, created_at
            from telegram_link_codes
            where user_id = ? and used_at is null
            order by created_at desc
            limit 1
            """,
            (user_id,),
        ).fetchone()
    active_code = None
    if code and _parse_datetime(code["expires_at"]) and _parse_datetime(code["expires_at"]) > _utc_now():
        active_code = dict(code)
    return {"user": dict(user) if user else None, "active_code": active_code, "ttl_minutes": LINK_CODE_TTL_MINUTES}


def resolve_telegram_user(telegram_id):
    if not telegram_id:
        return None
    with db() as conn:
        ensure_telegram_link_schema(conn)
        user = conn.execute(
            """
            select *
            from users
            where telegram_id = ? and status = 'ativo'
            """,
            (str(telegram_id),),
        ).fetchone()
        if user:
            conn.execute("update users set last_interaction_at = current_timestamp where id = ?", (user["id"],))
            return user["id"]
    return None


def link_telegram_account(code, telegram_user):
    clean_code = (code or "").strip().upper()
    if not clean_code:
        raise ValueError("Envie o codigo no formato: /vincular MGF-123456")

    telegram_id = str(telegram_user.id)
    username = getattr(telegram_user, "username", None)
    first_name = getattr(telegram_user, "first_name", None)
    now = _utc_now()

    with db() as conn:
        ensure_telegram_link_schema(conn)
        link_code = conn.execute(
            """
            select *
            from telegram_link_codes
            where code = ?
            """,
            (clean_code,),
        ).fetchone()
        if not link_code:
            raise ValueError("Codigo de vinculacao nao encontrado.")
        if link_code["used_at"]:
            raise ValueError("Esse codigo ja foi usado. Gere um novo codigo em Configuracoes > Telegram.")
        if _parse_datetime(link_code["expires_at"]) <= now:
            raise ValueError("Esse codigo expirou. Gere um novo codigo em Configuracoes > Telegram.")

        existing = conn.execute(
            "select id from users where telegram_id = ? and id != ?",
            (telegram_id, link_code["user_id"]),
        ).fetchone()
        if existing:
            conn.execute(
                """
                update users
                set telegram_id = null,
                    telegram_username = null,
                    telegram_first_name = null
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
                last_interaction_at = current_timestamp
            where id = ?
            """,
            (telegram_id, username, first_name, link_code["user_id"]),
        )
        conn.execute("update telegram_link_codes set used_at = current_timestamp where id = ?", (link_code["id"],))
        user = conn.execute("select name from users where id = ?", (link_code["user_id"],)).fetchone()
    return {"user_id": link_code["user_id"], "name": user["name"] if user else ""}


def unlink_telegram_account(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        conn.execute(
            """
            update users
            set telegram_id = null,
                telegram_username = null,
                telegram_first_name = null
            where id = ?
            """,
            (user_id,),
        )
        conn.execute("update telegram_link_codes set used_at = current_timestamp where user_id = ? and used_at is null", (user_id,))
    return True
