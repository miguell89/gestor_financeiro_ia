import json

from app.database import db


def create_log(level, source, action, message="", user_id=None, telegram_id=None, details=None):
    with db() as conn:
        conn.execute(
            """
            insert into system_logs
              (level, source, user_id, telegram_id, action, message, details_json)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                level,
                source,
                user_id,
                telegram_id,
                action,
                message,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )


def list_logs(limit=200, user_id=None):
    params = []
    where = ""
    if user_id:
        where = "where l.user_id = ?"
        params.append(user_id)

    params.append(limit)
    with db() as conn:
        return conn.execute(
            f"""
            select l.*, u.name as user_name
            from system_logs l
            left join users u on u.id = l.user_id
            {where}
            order by l.created_at desc, l.id desc
            limit ?
            """,
            params,
        ).fetchall()
