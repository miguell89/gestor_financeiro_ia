from datetime import date, datetime
import math
import re

from app.database import db
from app.services.finance_service import money, selected_month_year

GOAL_TYPES = ["Reserva de emergencia", "Imovel", "Veiculo", "Viagem", "Educacao", "Investimentos", "Reforma", "Outros"]
GOAL_STATUSES = ["no_ritmo", "atrasada", "concluida", "pausada"]
CONTRIBUTION_SOURCES = ["manual", "receita", "lancamento", "telegram", "IA"]


def brl(value):
    formatted = f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def month_end_prefix(month=None, year=None):
    month, year = selected_month_year(month, year)
    return f"{year:04d}-{month:02d}"


def add_months(base, months):
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = min(base.day, 28)
    return date(year, month, day)


def month_diff(start, end):
    return max((end.year - start.year) * 12 + end.month - start.month, 0)


def parse_date(value, fallback=None):
    if not value:
        return fallback
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return fallback


def normalize_status(value):
    value = (value or "no_ritmo").lower()
    aliases = {"No ritmo": "no_ritmo", "Atrasada": "atrasada", "Concluida": "concluida", "Concluída": "concluida", "Pausada": "pausada"}
    value = aliases.get(value, value)
    return value if value in GOAL_STATUSES else "no_ritmo"


def status_label(value):
    return {"no_ritmo": "No ritmo", "atrasada": "Atrasada", "concluida": "Concluida", "pausada": "Pausada"}.get(value, "No ritmo")


def goal_payload(form):
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("Nome da meta e obrigatorio")
    target = money(form.get("target_amount"))
    if target <= 0:
        raise ValueError("Valor objetivo deve ser maior que zero")
    current = money(form.get("current_amount") or form.get("initial_amount") or 0)
    return {
        "name": name,
        "description": (form.get("description") or "").strip(),
        "type": form.get("type") or "Outros",
        "target_amount": target,
        "current_amount": current,
        "monthly_target_amount": money(form.get("monthly_target_amount")),
        "start_date": form.get("start_date") or date.today().isoformat(),
        "deadline_date": form.get("deadline_date") or None,
        "icon": (form.get("icon") or name[:1] or "G").strip()[:3],
        "color": form.get("color") or "#8b5cf6",
        "status": normalize_status(form.get("status")),
    }


def calculate_goal(row, contributions=None, month=None, year=None):
    data = dict(row)
    target = money(data["target_amount"])
    base_current = money(data["current_amount"])
    contributions = contributions or []
    prefix = month_end_prefix(month, year)
    contribution_total = sum(money(item["amount"]) for item in contributions if (item["contribution_date"] or "")[:7] <= prefix)
    current = base_current + contribution_total
    missing = max(target - current, 0)
    percent = min(round((current / target) * 100), 100) if target else 0
    selected_month, selected_year = selected_month_year(month, year)
    selected_date = date(selected_year, selected_month, 1)
    start = parse_date(data.get("start_date"), selected_date) or selected_date
    deadline = parse_date(data.get("deadline_date"))
    months_elapsed = max(month_diff(start, selected_date) + 1, 1)
    avg_monthly = contribution_total / months_elapsed if months_elapsed else 0
    planned_monthly = money(data.get("monthly_target_amount"))
    required_monthly = 0
    if deadline:
        months_remaining = max(month_diff(selected_date, deadline), 1)
        required_monthly = missing / months_remaining if missing else 0
    else:
        months_remaining = math.ceil(missing / planned_monthly) if planned_monthly and missing else 0
    pace = avg_monthly or planned_monthly
    estimated_date = add_months(selected_date, math.ceil(missing / pace)) if pace and missing else selected_date
    status = normalize_status(data.get("status"))
    if percent >= 100:
        status = "concluida"
    elif status != "pausada" and deadline and selected_date > deadline and missing > 0:
        status = "atrasada"
    elif status != "pausada" and planned_monthly and avg_monthly + 1 < planned_monthly and months_elapsed > 1:
        status = "atrasada"
    planned_total = planned_monthly * months_elapsed
    data.update(
        {
            "current_calculated": current,
            "contribution_total": contribution_total,
            "missing_amount": missing,
            "percent": percent,
            "months_remaining": months_remaining,
            "avg_monthly": avg_monthly,
            "required_monthly": required_monthly,
            "estimated_completion": estimated_date.isoformat(),
            "estimated_completion_label": estimated_date.strftime("%b/%Y"),
            "planned_vs_realized": current - planned_total,
            "status": status,
            "status_label": status_label(status),
        }
    )
    return data


def list_goal_contributions(user_id, goal_id=None):
    params = [user_id]
    where = "user_id = ?"
    if goal_id:
        where += " and goal_id = ?"
        params.append(goal_id)
    with db() as conn:
        return conn.execute(
            f"""
            select *
            from goal_contributions
            where {where}
            order by contribution_date desc, id desc
            """,
            params,
        ).fetchall()


def list_goals(user_id, month=None, year=None, include_archived=True):
    with db() as conn:
        rows = conn.execute(
            """
            select *
            from goals
            where user_id = ?
            order by case status when 'concluida' then 3 when 'pausada' then 2 else 1 end, created_at desc
            """,
            (user_id,),
        ).fetchall()
        contributions = conn.execute("select * from goal_contributions where user_id = ?", (user_id,)).fetchall()
    by_goal = {}
    for item in contributions:
        by_goal.setdefault(item["goal_id"], []).append(item)
    return [calculate_goal(row, by_goal.get(row["id"], []), month, year) for row in rows if include_archived or row["status"] != "concluida"]


def get_goal(goal_id, user_id, month=None, year=None):
    with db() as conn:
        row = conn.execute("select * from goals where id = ? and user_id = ?", (goal_id, user_id)).fetchone()
    if not row:
        return None
    return calculate_goal(row, list_goal_contributions(user_id, goal_id), month, year)


def create_goal(form, user_id):
    payload = goal_payload(form)
    with db() as conn:
        cursor = conn.execute(
            """
            insert into goals
              (user_id, name, description, type, target_amount, current_amount, monthly_target_amount,
               start_date, deadline_date, icon, color, status)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload["description"],
                payload["type"],
                payload["target_amount"],
                payload["current_amount"],
                payload["monthly_target_amount"],
                payload["start_date"],
                payload["deadline_date"],
                payload["icon"],
                payload["color"],
                payload["status"],
            ),
        )
        return cursor.lastrowid


def update_goal(goal_id, form, user_id):
    payload = goal_payload(form)
    with db() as conn:
        conn.execute(
            """
            update goals
            set name = ?, description = ?, type = ?, target_amount = ?, current_amount = ?,
                monthly_target_amount = ?, start_date = ?, deadline_date = ?, icon = ?, color = ?,
                status = ?, updated_at = current_timestamp
            where id = ? and user_id = ?
            """,
            (
                payload["name"],
                payload["description"],
                payload["type"],
                payload["target_amount"],
                payload["current_amount"],
                payload["monthly_target_amount"],
                payload["start_date"],
                payload["deadline_date"],
                payload["icon"],
                payload["color"],
                payload["status"],
                goal_id,
                user_id,
            ),
        )
    return get_goal(goal_id, user_id)


def add_goal_contribution(goal_id, user_id, amount, contribution_date=None, source="manual", source_id=None, notes=None):
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Valor da contribuicao deve ser maior que zero")
    if not get_goal(goal_id, user_id):
        raise ValueError("Meta nao encontrada")
    contribution_date = contribution_date or date.today().isoformat()
    source = source if source in CONTRIBUTION_SOURCES else "manual"
    with db() as conn:
        cursor = conn.execute(
            """
            insert into goal_contributions (goal_id, user_id, amount, contribution_date, source, source_id, notes)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (goal_id, user_id, amount, contribution_date, source, source_id, notes),
        )
        goal = conn.execute("select * from goals where id = ? and user_id = ?", (goal_id, user_id)).fetchone()
        total = conn.execute("select coalesce(sum(amount), 0) as total from goal_contributions where goal_id = ? and user_id = ?", (goal_id, user_id)).fetchone()["total"]
        if money(goal["current_amount"]) + money(total) >= money(goal["target_amount"]):
            conn.execute("update goals set status = 'concluida', updated_at = current_timestamp where id = ? and user_id = ?", (goal_id, user_id))
        return cursor.lastrowid


def update_goal_status(goal_id, user_id, status):
    status = normalize_status(status)
    with db() as conn:
        conn.execute("update goals set status = ?, updated_at = current_timestamp where id = ? and user_id = ?", (status, goal_id, user_id))
    return get_goal(goal_id, user_id)


def delete_goal(goal_id, user_id):
    with db() as conn:
        conn.execute("delete from goal_contributions where goal_id = ? and user_id = ?", (goal_id, user_id))
        conn.execute("delete from goals where id = ? and user_id = ?", (goal_id, user_id))
    return True


def summarize_goals(user_id, month=None, year=None):
    goals = list_goals(user_id, month, year)
    total_target = sum(money(goal["target_amount"]) for goal in goals)
    total_current = sum(money(goal["current_calculated"]) for goal in goals)
    active = [goal for goal in goals if goal["status"] not in ("concluida", "pausada")]
    avg_monthly = sum(money(goal["avg_monthly"] or goal["monthly_target_amount"]) for goal in active)
    missing = sum(money(goal["missing_amount"]) for goal in active)
    months = math.ceil(missing / avg_monthly) if avg_monthly and missing else 0
    selected_month, selected_year = selected_month_year(month, year)
    conclusion = add_months(date(selected_year, selected_month, 1), months) if months else date(selected_year, selected_month, 1)
    return {
        "total_goals": len(goals),
        "total_target": total_target,
        "total_current": total_current,
        "avg_monthly": avg_monthly,
        "completion_forecast": conclusion.strftime("%B/%Y"),
        "completed_goals": len([goal for goal in goals if goal["status"] == "concluida"]),
        "late_goals": len([goal for goal in goals if goal["status"] == "atrasada"]),
        "average_percent": round((total_current / total_target) * 100) if total_target else 0,
    }


def goal_distribution(user_id, month=None, year=None):
    goals = list_goals(user_id, month, year)
    total = sum(money(goal["current_calculated"]) for goal in goals) or 1
    return [
        {
            "name": goal["name"],
            "total": goal["current_calculated"],
            "percent": round((money(goal["current_calculated"]) / total) * 100),
            "color": goal["color"],
        }
        for goal in goals
    ]


def goals_suggestions(user_id, month=None, year=None):
    goals = list_goals(user_id, month, year)
    suggestions = []
    for goal in goals:
        if goal["status"] == "atrasada":
            extra = max(goal["required_monthly"] - money(goal["avg_monthly"] or goal["monthly_target_amount"]), 0)
            suggestions.append(f"Sua meta {goal['name']} esta atrasada. Para recuperar, guarde {brl(extra)} a mais por mes.")
        elif goal["percent"] < 30 and goal["monthly_target_amount"]:
            suggestions.append(f"Voce pode aumentar suas economias em {brl(200)} por mes e acelerar {goal['name']}.")
        elif goal["status"] == "concluida":
            suggestions.append(f"Meta {goal['name']} concluida. Que tal criar uma nova meta de investimentos?")
    if not suggestions:
        suggestions.append("Suas metas estao organizadas. Continue acompanhando as contribuicoes todo mes.")
    if not any("invest" in item.lower() for item in suggestions):
        suggestions.append("Que tal criar uma meta para investimentos?")
    return suggestions[:4]


def goals_page_data(user_id, month=None, year=None):
    goals = list_goals(user_id, month, year)
    return {
        "goals": goals,
        "summary": summarize_goals(user_id, month, year),
        "distribution": goal_distribution(user_id, month, year),
        "suggestions": goals_suggestions(user_id, month, year),
        "types": GOAL_TYPES,
        "statuses": GOAL_STATUSES,
        "sources": CONTRIBUTION_SOURCES,
        "contributions": [dict(item) for item in list_goal_contributions(user_id)[:20]],
    }


def find_goal_by_text(user_id, text):
    normalized = (text or "").lower()
    goals = list_goals(user_id)
    for goal in goals:
        words = re.findall(r"\w+", goal["name"].lower())
        if any(word and word in normalized for word in words):
            return goal
    return goals[0] if goals else None
