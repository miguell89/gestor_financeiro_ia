from werkzeug.security import generate_password_hash

from app.database import db
from app.services.finance_service import get_dashboard_data
from app.services.log_service import list_logs
from app.services.telegram_link_service import ensure_telegram_link_schema


def list_users(filters):
    params = []
    clauses = []

    query = filters.get("q")
    status = filters.get("status")

    if query:
        clauses.append("(lower(u.name) like lower(?) or lower(u.email) like lower(?) or u.telegram_id like ?)")
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])

    if status:
        clauses.append("u.status = ?")
        params.append(status)

    where = f"where {' and '.join(clauses)}" if clauses else ""

    with db() as conn:
        ensure_telegram_link_schema(conn)
        return conn.execute(
            f"""
            select
              u.id,
              u.name,
              u.email,
              u.telegram_id,
              u.telegram_username,
              u.telegram_first_name,
              u.role,
              u.status,
              u.created_at,
              u.last_login_at,
              u.last_interaction_at,
              count(t.id) as total_transactions
            from users u
            left join transactions t on t.user_id = u.id
            {where}
            group by u.id
            order by u.created_at desc
            """,
            params,
        ).fetchall()


def get_user(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        return conn.execute("select * from users where id = ?", (user_id,)).fetchone()


def update_user(user_id, form):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        conn.execute(
            """
            update users
            set name = ?, email = ?, telegram_id = ?, telegram_username = ?, telegram_first_name = ?, role = ?, status = ?
            where id = ?
            """,
            (
                form.get("name"),
                form.get("email") or None,
                form.get("telegram_id") or None,
                form.get("telegram_username") or None,
                form.get("telegram_first_name") or None,
                form.get("role"),
                form.get("status"),
                user_id,
            ),
        )

        if form.get("password"):
            conn.execute(
                "update users set password_hash = ? where id = ?",
                (generate_password_hash(form.get("password")), user_id),
            )


def toggle_user_status(user_id):
    with db() as conn:
        user = conn.execute("select status from users where id = ?", (user_id,)).fetchone()
        new_status = "inativo" if user and user["status"] == "ativo" else "ativo"
        conn.execute("update users set status = ? where id = ?", (new_status, user_id))


def user_details(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        user = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
        transactions = conn.execute(
            """
            select t.*, c.name as category_name
            from transactions t
            left join categories c on c.id = t.category_id
            where t.user_id = ?
            order by t.date desc, t.id desc
            limit 12
            """,
            (user_id,),
        ).fetchall()
        bills = conn.execute(
            """
            select f.*, c.name as category_name
            from fixed_bills f
            left join categories c on c.id = f.category_id
            where f.user_id = ?
            order by f.due_day asc
            """,
            (user_id,),
        ).fetchall()
        attachments = conn.execute(
            """
            select *
            from financial_attachments
            where user_id = ?
            order by created_at desc
            limit 12
            """,
            (user_id,),
        ).fetchall()

    return {
        "user": user,
        "summary": get_dashboard_data(user_id),
        "transactions": transactions,
        "bills": bills,
        "attachments": attachments,
        "logs": list_logs(user_id=user_id),
    }
