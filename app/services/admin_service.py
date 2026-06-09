from werkzeug.security import generate_password_hash

from app.database import db
from app.services.finance_service import get_dashboard_data
from app.services.log_service import list_logs
from app.services.telegram_link_service import ensure_telegram_link_schema


def validate_role(role):
    return role if role in {"admin", "user"} else "user"


def validate_status(status):
    return status if status in {"ativo", "inativo"} else "ativo"


def checkbox_value(form, key):
    return 1 if form.get(key) in {"1", "on", "true", "sim"} else 0


def telegram_label(status):
    return {
        "conectado": "Conectado",
        "pendente": "Pendente",
        "nao_conectado": "Não conectado",
    }.get(status or "nao_conectado", "Não conectado")


def telegram_badge(status):
    return {
        "conectado": "🟢 Conectado",
        "pendente": "🟡 Pendente",
        "nao_conectado": "🔴 Não conectado",
    }.get(status or "nao_conectado", "🔴 Não conectado")


def list_users(filters):
    params = []
    clauses = []

    query = filters.get("q")
    status = filters.get("status")

    if query:
        clauses.append("(lower(u.name) like lower(?) or lower(u.email) like lower(?) or u.telegram_id like ? or lower(u.telegram_username) like lower(?))")
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"])

    if status:
        clauses.append("u.status = ?")
        params.append(status)

    where = f"where {' and '.join(clauses)}" if clauses else ""

    with db() as conn:
        ensure_telegram_link_schema(conn)
        rows = conn.execute(
            f"""
            select
              u.id,
              u.name,
              u.email,
              u.telegram_id,
              u.telegram_username,
              u.telegram_first_name,
              u.telegram_status,
              u.telegram_link_code,
              u.telegram_linked_at,
              u.telegram_last_interaction,
              u.role,
              u.status,
              u.created_at,
              u.last_login_at,
              u.last_interaction_at,
              (select count(*) from transactions t where t.user_id = u.id) as total_transactions
            from users u
            {where}
            order by u.created_at desc
            """,
            params,
        ).fetchall()
    return [dict(row, telegram_badge=telegram_badge(row["telegram_status"])) for row in rows]


def admin_kpis():
    with db() as conn:
        ensure_telegram_link_schema(conn)
        row = conn.execute(
            """
            select
              count(*) as total_users,
              sum(case when telegram_status = 'conectado' then 1 else 0 end) as telegram_connected,
              sum(case when telegram_status = 'pendente' then 1 else 0 end) as telegram_pending,
              sum(case when status = 'inativo' then 1 else 0 end) as inactive_users
            from users
            """
        ).fetchone()
    return {
        "total_users": row["total_users"] or 0,
        "telegram_connected": row["telegram_connected"] or 0,
        "telegram_pending": row["telegram_pending"] or 0,
        "inactive_users": row["inactive_users"] or 0,
    }


def create_user(form):
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    if not name:
        raise ValueError("Informe o nome do usuário.")
    if not email:
        raise ValueError("Informe o e-mail do usuário.")
    if not password:
        raise ValueError("Informe uma senha inicial.")

    with db() as conn:
        ensure_telegram_link_schema(conn)
        existing = conn.execute("select id from users where lower(email) = lower(?)", (email,)).fetchone()
        if existing:
            raise ValueError("Já existe um usuário com esse e-mail.")
        cursor = conn.execute(
            """
            insert into users
              (name, email, password_hash, role, status, assistant_tone,
               telegram_status, receive_telegram_alerts, receive_telegram_reports,
               receive_telegram_bill_reminders, receive_telegram_ai_analysis)
            values (?, ?, ?, ?, ?, 'divertido', 'nao_conectado', ?, ?, ?, ?)
            """,
            (
                name,
                email,
                generate_password_hash(password),
                validate_role(form.get("role")),
                validate_status(form.get("status")),
                checkbox_value(form, "receive_telegram_alerts"),
                checkbox_value(form, "receive_telegram_reports"),
                checkbox_value(form, "receive_telegram_bill_reminders"),
                checkbox_value(form, "receive_telegram_ai_analysis"),
            ),
        )
        return cursor.lastrowid


def get_user(user_id):
    with db() as conn:
        ensure_telegram_link_schema(conn)
        return conn.execute("select * from users where id = ?", (user_id,)).fetchone()


def update_user(user_id, form):
    email = (form.get("email") or "").strip().lower()
    if not (form.get("name") or "").strip():
        raise ValueError("Informe o nome do usuário.")
    if not email:
        raise ValueError("Informe o e-mail do usuário.")
    with db() as conn:
        ensure_telegram_link_schema(conn)
        duplicate = conn.execute("select id from users where lower(email) = lower(?) and id != ?", (email, user_id)).fetchone()
        if duplicate:
            raise ValueError("Já existe outro usuário com esse e-mail.")
        conn.execute(
            """
            update users
            set name = ?, email = ?, role = ?, status = ?,
                receive_telegram_alerts = ?,
                receive_telegram_reports = ?,
                receive_telegram_bill_reminders = ?,
                receive_telegram_ai_analysis = ?
            where id = ?
            """,
            (
                form.get("name"),
                email,
                validate_role(form.get("role")),
                validate_status(form.get("status")),
                checkbox_value(form, "receive_telegram_alerts"),
                checkbox_value(form, "receive_telegram_reports"),
                checkbox_value(form, "receive_telegram_bill_reminders"),
                checkbox_value(form, "receive_telegram_ai_analysis"),
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
        "telegram_badge": telegram_badge(user["telegram_status"] if user else "nao_conectado"),
        "summary": get_dashboard_data(user_id),
        "transactions": transactions,
        "bills": bills,
        "attachments": attachments,
        "logs": list_logs(user_id=user_id),
    }
