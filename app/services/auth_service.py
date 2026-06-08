from functools import wraps

from flask import abort, redirect, session, url_for
from werkzeug.security import check_password_hash

from app.database import db


def authenticate(email, password):
    with db() as conn:
        user = conn.execute("select * from users where lower(email) = lower(?)", (email,)).fetchone()

    if not user or not user["password_hash"] or user["status"] != "ativo":
        return None

    if not check_password_hash(user["password_hash"], password):
        return None

    with db() as conn:
        conn.execute("update users set last_login_at = current_timestamp where id = ?", (user["id"],))

    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("web.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("web.login"))
        if session["user"].get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def current_user_id():
    user = session.get("user")
    return user["id"] if user else None


def is_admin():
    user = session.get("user")
    return bool(user and user.get("role") == "admin")
