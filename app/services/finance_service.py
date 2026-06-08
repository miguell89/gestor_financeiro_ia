from datetime import date, timedelta

from app.database import db
from ai.response_generator import gerar_resposta_humanizada
from config.settings import settings


def money(value):
    return float(value or 0)


def current_month_prefix():
    return date.today().strftime("%Y-%m")


def selected_month_year(month=None, year=None):
    today = date.today()
    return int(month or today.month), int(year or today.year)


def month_prefix(month=None, year=None):
    month, year = selected_month_year(month, year)
    return f"{year:04d}-{month:02d}"


def legacy_bill_status(status):
    return {
        "paid": "pago",
        "pending": "pendente",
        "overdue": "atrasado",
        "postponed": "adiado",
        "canceled": "cancelado",
        "pago": "pago",
        "pendente": "pendente",
        "atrasado": "atrasado",
        "adiado": "adiado",
        "cancelado": "cancelado",
    }.get(status or "pending", "pendente")


def occurrence_status(status):
    return {
        "pago": "paid",
        "pendente": "pending",
        "atrasado": "overdue",
        "adiado": "postponed",
        "cancelado": "canceled",
        "paid": "paid",
        "pending": "pending",
        "overdue": "overdue",
        "postponed": "postponed",
        "canceled": "canceled",
    }.get(status or "pending", "pending")


def generate_monthly_fixed_bill_occurrences(user_id, month=None, year=None):
    month, year = selected_month_year(month, year)
    with db() as conn:
        bills = conn.execute(
            """
            select *
            from fixed_bills
            where user_id = ?
              and coalesce(active, 1) = 1
              and lower(coalesce(status, 'ativa')) not in ('inativa', 'cancelada')
            """,
            (user_id,),
        ).fetchall()
        for bill in bills:
            due_day = min(int(bill["due_day"] or 1), 28)
            due_date = date(year, month, due_day).isoformat()
            is_installment = truthy(bill["is_installment"] if "is_installment" in bill.keys() else 0)
            installment_number = None
            total_installments = None
            amount = money(bill["default_amount"] if "default_amount" in bill.keys() else bill["expected_amount"])
            notes = None
            if is_installment:
                total_installments = int(bill["total_installments"] or 0)
                start_raw = bill["installment_start_date"] or bill["start_date"] or due_date
                start_date = date.fromisoformat(start_raw[:10])
                installment_number = (year - start_date.year) * 12 + (month - start_date.month) + 1
                if installment_number < 1 or installment_number > total_installments:
                    continue
                amount = money(bill["installment_amount"] or bill["expected_amount"])
                notes = f"Parcela {installment_number}/{total_installments}"
            conn.execute(
                """
                insert or ignore into fixed_bill_occurrences
                  (fixed_bill_id, user_id, reference_month, reference_year, due_date, amount, status,
                   installment_number, total_installments, is_installment_occurrence, original_default_amount, notes)
                values (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    bill["id"],
                    user_id,
                    month,
                    year,
                    due_date,
                    amount,
                    installment_number,
                    total_installments,
                    1 if is_installment else 0,
                    bill["default_amount"] if "default_amount" in bill.keys() else bill["expected_amount"],
                    notes,
                ),
            )
            if truthy(bill["ask_value_before_generate"] if "ask_value_before_generate" in bill.keys() else 0):
                message = (
                    f"{bill['name']} vence em {due_day:02d}/{month:02d}. "
                    f"O valor continua R$ {amount:,.2f}?"
                )
                exists = conn.execute(
                    """
                    select id from alerts
                    where user_id = ? and type = 'fixed_bill_value_confirmation'
                      and scheduled_for = ? and message = ?
                    """,
                    (user_id, due_date, message),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """
                        insert into alerts
                          (user_id, type, message, status, scheduled_for, reference_month, reference_year)
                        values (?, 'fixed_bill_value_confirmation', ?, 'pendente', ?, ?, ?)
                        """,
                        (user_id, message, due_date, month, year),
                    )


def fixed_bill_base_status(status):
    value = (status or "ativa").lower()
    if value in ("inativa", "inactive"):
        return "inativa"
    if value in ("cancelada", "cancelado", "canceled"):
        return "cancelada"
    return "ativa"


def fixed_bill_form_payload(form, month=None, year=None):
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("Nome da conta e obrigatorio")
    if not form.get("category_id"):
        raise ValueError("Categoria e obrigatoria")

    default_amount = money(form.get("default_amount") or form.get("expected_amount") or 0)
    if default_amount < 0:
        raise ValueError("Valor padrao nao pode ser negativo")
    if default_amount == 0:
        raise ValueError("Valor padrao e obrigatorio")

    due_day = int(form.get("due_day") or 0)
    if due_day < 1 or due_day > 31:
        raise ValueError("Dia do vencimento deve ficar entre 1 e 31")
    if not form.get("payment_method"):
        raise ValueError("Forma de pagamento e obrigatoria")

    recurrence = form.get("recurrence_interval") or form.get("recurrence") or "mensal"
    status = fixed_bill_base_status(form.get("status"))
    is_installment = truthy(form.get("is_installment"))
    total_installments = int(form.get("total_installments") or 0)
    installment_amount = money(form.get("installment_amount") or default_amount)
    paid_installments = int(form.get("paid_installments") or 0)
    if is_installment:
        if total_installments < 1:
            raise ValueError("Numero de parcelas deve ser maior que zero")
        if installment_amount <= 0:
            raise ValueError("Valor da parcela e obrigatorio")
        if paid_installments > total_installments:
            raise ValueError("Parcelas pagas nao pode ser maior que total de parcelas")
    else:
        total_installments = None
        installment_amount = None
        paid_installments = 0

    start_date = form.get("start_date") or selected_period_date(month, year, due_day)
    installment_start_date = form.get("installment_start_date") or start_date
    return {
        "name": name,
        "category_id": form.get("category_id") or None,
        "default_amount": default_amount,
        "expected_amount": installment_amount if is_installment else default_amount,
        "due_day": due_day,
        "payment_method": form.get("payment_method"),
        "status": status,
        "active": 1 if status == "ativa" else 0,
        "recurrence": recurrence,
        "recurrence_type": recurrence,
        "recurrence_interval": recurrence,
        "start_date": start_date,
        "alert_days_before": int(form.get("alert_days_before") or 1),
        "ask_value_before_generate": 1 if truthy(form.get("ask_value_before_generate")) else 0,
        "auto_update_default_value": 1 if truthy(form.get("auto_update_default_value")) else 0,
        "is_installment": 1 if is_installment else 0,
        "total_installments": total_installments,
        "installment_amount": installment_amount,
        "paid_installments": paid_installments,
        "installment_start_date": installment_start_date if is_installment else None,
        "installment_total_amount": money(form.get("installment_total_amount") or ((installment_amount or 0) * (total_installments or 0))),
        "notes": form.get("notes") or None,
    }


def current_month_transaction_date(due_day=None):
    today = date.today()
    day = min(int(due_day or today.day), 28)
    return today.replace(day=day).isoformat()


def selected_period_date(month=None, year=None, day=1):
    month, year = selected_month_year(month, year)
    day = min(max(int(day or 1), 1), 28)
    return date(year, month, day).isoformat()


def truthy(value):
    return str(value or "").lower() in ("1", "true", "on", "yes", "sim")


def add_months(base_date, months):
    month = base_date.month - 1 + months
    year = base_date.year + month // 12
    month = month % 12 + 1
    day = min(base_date.day, 28)
    return date(year, month, day)


def next_recurrence_date(base_date, interval):
    interval = (interval or "mensal").lower()
    if interval in ("15_dias", "quinzenal"):
        return base_date + timedelta(days=15)
    if interval in ("7_dias", "semanal"):
        return base_date + timedelta(days=7)
    if interval in ("anual", "1_ano"):
        return add_months(base_date, 12)
    return add_months(base_date, 1)


def previous_month_prefix(month=None, year=None):
    selected_month, selected_year = selected_month_year(month, year)
    first_day = date(selected_year, selected_month, 1)
    return (first_day - timedelta(days=1)).strftime("%Y-%m")


def percent_change(current, previous):
    current = money(current)
    previous = money(previous)
    if previous <= 0:
        return 100 if current > 0 else 0
    return round(((current - previous) / previous) * 100)


def _user_clause(user_id, alias=""):
    prefix = f"{alias}." if alias else ""
    return f" and {prefix}user_id = ?", [user_id]


def get_dashboard_data(user_id, month=None, year=None):
    selected_month, selected_year = selected_month_year(month, year)
    generate_monthly_fixed_bill_occurrences(user_id, selected_month, selected_year)
    month = month_prefix(selected_month, selected_year)
    previous_month = previous_month_prefix(selected_month, selected_year)
    with db() as conn:
        transactions = conn.execute(
            """
            select t.*, c.name as category_name, c.color as category_color
            from transactions t
            left join categories c on c.id = t.category_id
            where t.date like ? and t.user_id = ?
            order by t.date desc, t.id desc
            """,
            (f"{month}%", user_id),
        ).fetchall()

        previous_transactions = conn.execute(
            """
            select t.*, c.name as category_name, c.color as category_color
            from transactions t
            left join categories c on c.id = t.category_id
            where t.date like ? and t.user_id = ?
            order by t.date desc, t.id desc
            """,
            (f"{previous_month}%", user_id),
        ).fetchall()

        all_transactions = conn.execute(
            """
            select t.*, c.name as category_name, c.color as category_color
            from transactions t
            left join categories c on c.id = t.category_id
            where t.user_id = ?
            order by t.date desc, t.id desc
            limit 5
            """,
            (user_id,),
        ).fetchall()

        fixed_bills = conn.execute(
            """
            select
              f.id,
              f.user_id,
              f.name,
              f.category_id,
              f.expected_amount,
              f.due_day,
              f.recurrence,
              f.alert_days_before,
              o.id as occurrence_id,
              o.reference_month,
              o.reference_year,
              o.due_date,
              o.amount,
              o.status as occurrence_status,
              o.paid_at,
              o.postponed_to_month,
              o.postponed_to_year,
              o.transaction_id,
              c.name as category_name
            from fixed_bill_occurrences o
            join fixed_bills f on f.id = o.fixed_bill_id
            left join categories c on c.id = f.category_id
            where o.user_id = ?
              and o.reference_month = ?
              and o.reference_year = ?
            order by o.due_date asc
            """,
            (user_id, selected_month, selected_year),
        ).fetchall()

        categories = conn.execute("select * from categories order by name").fetchall()
        month_revenues = conn.execute(
            """
            select *
            from revenues
            where user_id = ?
              and expected_date like ?
              and status in ('prevista', 'atrasada')
            """,
            (user_id, f"{month}%"),
        ).fetchall()

    receitas = sum(money(t["amount"]) for t in transactions if t["type"] == "receita" and t["status"] == "pago")
    despesas = sum(money(t["amount"]) for t in transactions if t["type"] == "despesa" and t["status"] == "pago")
    receitas_previas = sum(money(t["amount"]) for t in previous_transactions if t["type"] == "receita" and t["status"] == "pago")
    despesas_previas = sum(money(t["amount"]) for t in previous_transactions if t["type"] == "despesa" and t["status"] == "pago")
    pendentes = sum(money(b["amount"]) for b in fixed_bills if b["occurrence_status"] == "pending")
    atrasadas = sum(money(b["amount"]) for b in fixed_bills if b["occurrence_status"] == "overdue")
    receitas_pendentes = sum(money(r["expected_amount"]) for r in month_revenues)
    saldo_atual = receitas - despesas
    saldo_previsto = saldo_atual + receitas_pendentes - pendentes - atrasadas
    economia_mes = max(saldo_atual, 0)

    category_totals = {}
    for item in transactions:
        if item["type"] != "despesa":
            continue
        name = item["category_name"] or "Sem categoria"
        category_totals[name] = category_totals.get(name, 0) + money(item["amount"])

    category_bars = []
    category_limits = {category["name"]: money(category["monthly_limit"]) for category in categories}
    for name, total in sorted(category_totals.items(), key=lambda item: item[1], reverse=True):
        percent = round((total / despesas) * 100) if despesas else 0
        limit_value = category_limits.get(name, 0)
        limit_percent = round((total / limit_value) * 100) if limit_value else percent
        category_bars.append(
            {
                "name": name,
                "total": total,
                "percent": min(percent, 100),
                "limit_percent": limit_percent,
            }
        )

    paid_count = len([b for b in fixed_bills if b["occurrence_status"] == "paid"])
    pending_count = len([b for b in fixed_bills if b["occurrence_status"] == "pending"])
    late_count = len([b for b in fixed_bills if b["occurrence_status"] == "overdue"])
    total_bills = max(len(fixed_bills), 1)
    paid_percent = round((paid_count / total_bills) * 100)
    budget_percent = round((despesas / receitas) * 100) if receitas else 0
    near_limit_count = len([item for item in category_bars if 75 <= item["limit_percent"] < 100])
    over_limit_count = len([item for item in category_bars if item["limit_percent"] >= 100])
    health_score = max(0, min(100, 100 - late_count * 18 - over_limit_count * 10 - near_limit_count * 5 - max(budget_percent - 80, 0)))
    health_status = "Boa"
    if health_score < 55:
        health_status = "Critica"
    elif health_score < 75:
        health_status = "Atencao"

    goal_target = 500.0
    goal_current = min(economia_mes, goal_target)
    goal_percent = round((goal_current / goal_target) * 100) if goal_target else 0
    goal_missing = max(goal_target - goal_current, 0)

    prioritized_bills = []
    today = date.today()
    for bill in fixed_bills:
        due_date = date.fromisoformat(bill["due_date"])
        days_left = (due_date - today).days
        if bill["occurrence_status"] == "overdue" or days_left < 0:
            priority = "Vence hoje"
            priority_class = "danger"
        elif days_left == 0:
            priority = "Vence hoje"
            priority_class = "danger"
        elif days_left == 1:
            priority = "Vence amanha"
            priority_class = "warning"
        elif days_left <= 7:
            priority = "Proxima semana"
            priority_class = "success"
        else:
            priority = "Em breve"
            priority_class = "info"
        item = dict(bill)
        item["status"] = legacy_bill_status(bill["occurrence_status"])
        item["expected_amount"] = bill["amount"]
        item["due_day"] = due_date.day
        item.update({"priority": priority, "priority_class": priority_class})
        prioritized_bills.append(item)

    alerts = []
    if late_count:
        alerts.append({"type": "danger", "title": "Contas atrasadas", "message": f"{late_count} conta(s) precisam de atencao."})
    if over_limit_count:
        alerts.append({"type": "danger", "title": "Categorias acima do limite", "message": f"{over_limit_count} categoria(s) passaram do planejado."})
    if pending_count:
        alerts.append({"type": "warning", "title": "Vencimentos proximos", "message": f"{pending_count} conta(s) ainda pendentes."})
    if goal_percent < 70:
        alerts.append({"type": "warning", "title": "Meta em risco", "message": "A economia do mes esta abaixo do alvo."})
    if not alerts:
        alerts.append({"type": "success", "title": "Tudo sob controle", "message": "Nenhum alerta critico neste momento."})

    top_category = category_bars[0] if category_bars else {"name": "Alimentacao", "percent": 0}
    assistant_message = gerar_resposta_humanizada(
        "resumo_dashboard",
        {
            "saldo_previsto": saldo_previsto,
            "despesas": despesas,
            "receitas": receitas,
            "percentual_orcamento": 72,
        },
        settings.ASSISTANT_TONE,
    )

    return {
        "saldo_atual": saldo_atual,
        "receitas": receitas,
        "despesas": despesas,
        "saldo_previsto": saldo_previsto,
        "economia_mes": economia_mes,
        "receitas_previas": receitas_previas,
        "despesas_previas": despesas_previas,
        "receitas_delta": percent_change(receitas, receitas_previas),
        "despesas_delta": percent_change(despesas, despesas_previas),
        "saldo_delta": percent_change(saldo_atual, receitas_previas - despesas_previas),
        "contas_pagas": paid_count,
        "contas_pendentes": pending_count,
        "contas_atrasadas": late_count,
        "paid_percent": paid_percent,
        "budget_percent": budget_percent,
        "near_limit_count": near_limit_count,
        "over_limit_count": over_limit_count,
        "health_score": health_score,
        "health_status": health_status,
        "goal_current": goal_current,
        "goal_target": goal_target,
        "goal_percent": min(goal_percent, 100),
        "goal_missing": goal_missing,
        "category_totals": category_totals,
        "category_bars": category_bars[:6],
        "fixed_bills": prioritized_bills[:4],
        "latest_transactions": all_transactions,
        "categories": categories,
        "assistant_message": assistant_message,
        "alerts": alerts[:4],
        "top_category": top_category,
    }


def dashboard_api_data(user_id, month=None, year=None):
    data = get_dashboard_data(user_id, month=month, year=year)
    return {
        "saldo_atual": data["saldo_atual"],
        "receitas": data["receitas"],
        "despesas": data["despesas"],
        "saldo_previsto": data["saldo_previsto"],
        "contas_pagas": data["contas_pagas"],
        "contas_pendentes": data["contas_pendentes"],
        "contas_atrasadas": data["contas_atrasadas"],
        "gastos_por_categoria": data["category_totals"],
        "proximos_vencimentos": [dict(item) for item in data["fixed_bills"]],
        "ultimos_lancamentos": [dict(item) for item in data["latest_transactions"]],
    }


def list_transactions(user_id, origin=None, category_id=None, status=None, search=None, period=None, month=None, year=None):
    params = [user_id]
    origin_sql = ""
    if origin:
        origin_sql = " and lower(t.origin) = lower(?)"
        params.append(origin)
    category_sql = ""
    if category_id:
        category_sql = " and t.category_id = ?"
        params.append(category_id)
    status_sql = ""
    if status:
        status_sql = " and lower(t.status) = lower(?)"
        params.append(status)
    search_sql = ""
    if search:
        search_sql = " and (lower(t.description) like lower(?) or lower(c.name) like lower(?) or lower(t.origin) like lower(?))"
        term = f"%{search}%"
        params.extend([term, term, term])
    period_sql = ""
    if period:
        period_sql = " and t.date >= date('now', ?)"
        params.append(f"-{int(period)} days")
    elif month or year:
        period_sql = " and t.date like ?"
        params.append(f"{month_prefix(month, year)}%")

    with db() as conn:
        return conn.execute(
            f"""
            select t.*, c.name as category_name
            from transactions t
            left join categories c on c.id = t.category_id
            where t.user_id = ?{origin_sql}{category_sql}{status_sql}{search_sql}{period_sql}
            order by t.date desc, t.id desc
            """,
            params,
        ).fetchall()


def get_lancamentos_data(user_id, month=None, year=None):
    selected_month, selected_year = selected_month_year(month, year)
    month = month_prefix(selected_month, selected_year)
    previous_month = previous_month_prefix(selected_month, selected_year)
    with db() as conn:
        current_transactions = conn.execute(
            """
            select t.*, c.name as category_name
            from transactions t
            left join categories c on c.id = t.category_id
            where t.user_id = ? and t.date like ?
            """,
            (user_id, f"{month}%"),
        ).fetchall()
        previous_transactions = conn.execute(
            """
            select * from transactions
            where user_id = ? and date like ?
            """,
            (user_id, f"{previous_month}%"),
        ).fetchall()

    receitas = sum(money(t["amount"]) for t in current_transactions if t["type"] == "receita" and t["status"] == "pago")
    despesas = sum(money(t["amount"]) for t in current_transactions if t["type"] == "despesa" and t["status"] == "pago")
    receitas_previas = sum(money(t["amount"]) for t in previous_transactions if t["type"] == "receita" and t["status"] == "pago")
    despesas_previas = sum(money(t["amount"]) for t in previous_transactions if t["type"] == "despesa" and t["status"] == "pago")
    total_lancamentos = len(current_transactions)
    previous_total = len(previous_transactions)
    saldo = receitas - despesas
    previous_saldo = receitas_previas - despesas_previas
    media_diaria = despesas / max(date.today().day, 1)
    previous_media = despesas_previas / 30 if despesas_previas else 0

    category_totals = {}
    origin_totals = {}
    for item in current_transactions:
        if item["type"] == "despesa":
            category = item["category_name"] or "Sem categoria"
            category_totals[category] = category_totals.get(category, 0) + money(item["amount"])
        origin = item["origin"] or "manual"
        origin_totals[origin] = origin_totals.get(origin, 0) + 1

    category_bars = []
    for name, total in sorted(category_totals.items(), key=lambda item: item[1], reverse=True):
        category_bars.append({"name": name, "total": total, "percent": round((total / despesas) * 100) if despesas else 0})

    origin_bars = []
    for name, total in sorted(origin_totals.items(), key=lambda item: item[1], reverse=True):
        origin_bars.append({"name": name, "total": total, "percent": round((total / max(total_lancamentos, 1)) * 100)})

    return {
        "receitas": receitas,
        "despesas": despesas,
        "saldo": saldo,
        "total_lancamentos": total_lancamentos,
        "media_diaria": media_diaria,
        "receitas_delta": percent_change(receitas, receitas_previas),
        "despesas_delta": percent_change(despesas, despesas_previas),
        "saldo_delta": percent_change(saldo, previous_saldo),
        "total_delta": percent_change(total_lancamentos, previous_total),
        "media_delta": percent_change(media_diaria, previous_media),
        "category_bars": category_bars[:6],
        "origin_bars": origin_bars,
    }


def summarize_transactions(transactions):
    receitas = sum(money(t["amount"]) for t in transactions if t["type"] == "receita" and t["status"] == "pago")
    despesas = sum(money(t["amount"]) for t in transactions if t["type"] == "despesa" and t["status"] == "pago")
    saldo = receitas - despesas
    total_lancamentos = len(transactions)
    media_diaria = despesas / max(date.today().day, 1)

    category_totals = {}
    origin_totals = {}
    for item in transactions:
        if item["type"] == "despesa":
            category = item["category_name"] or "Sem categoria"
            category_totals[category] = category_totals.get(category, 0) + money(item["amount"])
        origin = item["origin"] or "manual"
        origin_totals[origin] = origin_totals.get(origin, 0) + 1

    category_bars = [
        {"name": name, "total": total, "percent": round((total / despesas) * 100) if despesas else 0}
        for name, total in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    origin_bars = [
        {"name": name, "total": total, "percent": round((total / max(total_lancamentos, 1)) * 100)}
        for name, total in sorted(origin_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "receitas": receitas,
        "despesas": despesas,
        "saldo": saldo,
        "total_lancamentos": total_lancamentos,
        "media_diaria": media_diaria,
        "receitas_delta": 0,
        "despesas_delta": 0,
        "saldo_delta": 0,
        "total_delta": 0,
        "media_delta": 0,
        "category_bars": category_bars[:6],
        "origin_bars": origin_bars,
    }


def get_transaction(transaction_id, user_id):
    with db() as conn:
        return conn.execute(
            """
            select t.*, c.name as category_name
            from transactions t
            left join categories c on c.id = t.category_id
            where t.id = ? and t.user_id = ?
            """,
            (transaction_id, user_id),
        ).fetchone()


def transaction_form_payload(form, month=None, year=None):
    transaction_date = form.get("date") or selected_period_date(month, year)
    amount = float(form.get("amount") or 0)
    description = (form.get("description") or "").strip()
    notes = (form.get("notes") or "").strip()
    if not form.get("type"):
        raise ValueError("Tipo do lancamento e obrigatorio")
    if not transaction_date:
        raise ValueError("Data e obrigatoria")
    if amount < 0:
        raise ValueError("Valor nao pode ser negativo")
    if amount <= 0:
        raise ValueError("Valor e obrigatorio")
    if not form.get("category_id"):
        raise ValueError("Categoria e obrigatoria")
    if not form.get("payment_method"):
        raise ValueError("Forma de pagamento e obrigatoria")
    if not form.get("status"):
        raise ValueError("Status e obrigatorio")
    if len(description) > 120:
        raise ValueError("Descricao deve ter no maximo 120 caracteres")
    if len(notes) > 200:
        raise ValueError("Observacao deve ter no maximo 200 caracteres")

    return {
        "type": form.get("type"),
        "date": transaction_date,
        "amount": amount,
        "category_id": form.get("category_id") or None,
        "description": description,
        "payment_method": form.get("payment_method"),
        "status": form.get("status"),
        "origin": form.get("origin", "manual"),
        "fixed_bill_id": form.get("fixed_bill_id") or None,
        "revenue_id": form.get("revenue_id") or None,
        "project_center": form.get("project_center") or None,
        "notes": notes,
        "is_recurring": 1 if truthy(form.get("is_recurring")) else 0,
        "recurrence_frequency": form.get("recurrence_frequency") or None,
        "recurrence_day": int(form.get("recurrence_day") or 0) or None,
        "recurrence_end_date": form.get("recurrence_end_date") or None,
        "reminder_enabled": 1 if truthy(form.get("reminder_enabled")) else 0,
        "split_enabled": 1 if truthy(form.get("split_enabled")) else 0,
        "receipt_path": form.get("receipt_path") or None,
    }


def create_transaction(form, user_id, month=None, year=None):
    payload = transaction_form_payload(form, month, year)
    with db() as conn:
        cursor = conn.execute(
            """
            insert into transactions
              (user_id, type, date, amount, category_id, description, payment_method, status, origin,
               fixed_bill_id, revenue_id, project_center, notes, is_recurring, recurrence_frequency,
               recurrence_day, recurrence_end_date, reminder_enabled, split_enabled, receipt_path)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, payload["type"], payload["date"], payload["amount"], payload["category_id"],
                payload["description"], payload["payment_method"], payload["status"], payload["origin"],
                payload["fixed_bill_id"], payload["revenue_id"], payload["project_center"], payload["notes"],
                payload["is_recurring"], payload["recurrence_frequency"], payload["recurrence_day"],
                payload["recurrence_end_date"], payload["reminder_enabled"], payload["split_enabled"], payload["receipt_path"],
            ),
        )
        if payload["fixed_bill_id"] and payload["status"] in ("pago", "pendente", "atrasado", "adiado", "cancelado"):
            conn.execute("update fixed_bills set status = ? where id = ? and user_id = ?", (payload["status"], payload["fixed_bill_id"], user_id))
        if payload["revenue_id"]:
            revenue_status = "recebida" if payload["status"] == "pago" else "prevista"
            conn.execute(
                "update revenues set status = ?, received_date = ? where id = ? and user_id = ?",
                (revenue_status, payload["date"] if revenue_status == "recebida" else None, payload["revenue_id"], user_id),
            )
        return cursor.lastrowid


def update_transaction(transaction_id, form, user_id):
    payload = transaction_form_payload(form)
    with db() as conn:
        conn.execute(
            """
            update transactions
            set type = ?, date = ?, amount = ?, category_id = ?, description = ?,
                payment_method = ?, status = ?, origin = ?, fixed_bill_id = ?, revenue_id = ?,
                project_center = ?, notes = ?, is_recurring = ?, recurrence_frequency = ?,
                recurrence_day = ?, recurrence_end_date = ?, reminder_enabled = ?, split_enabled = ?,
                receipt_path = coalesce(?, receipt_path)
            where id = ? and user_id = ?
            """,
            (
                payload["type"], payload["date"], payload["amount"], payload["category_id"], payload["description"],
                payload["payment_method"], payload["status"], payload["origin"], payload["fixed_bill_id"], payload["revenue_id"],
                payload["project_center"], payload["notes"], payload["is_recurring"], payload["recurrence_frequency"],
                payload["recurrence_day"], payload["recurrence_end_date"], payload["reminder_enabled"], payload["split_enabled"],
                payload["receipt_path"], transaction_id, user_id,
            ),
        )
        if payload["fixed_bill_id"] and payload["status"] in ("pago", "pendente", "atrasado", "adiado", "cancelado"):
            conn.execute("update fixed_bills set status = ? where id = ? and user_id = ?", (payload["status"], payload["fixed_bill_id"], user_id))
        if payload["revenue_id"]:
            revenue_status = "recebida" if payload["status"] == "pago" else "prevista"
            conn.execute(
                """
                update revenues
                set status = ?, received_date = ?, expected_amount = ?, name = ?
                where id = ? and user_id = ?
                """,
                (revenue_status, payload["date"] if revenue_status == "recebida" else None, payload["amount"], payload["description"], payload["revenue_id"], user_id),
            )


def set_transaction_receipt_path(transaction_id, user_id, receipt_path):
    with db() as conn:
        conn.execute(
            """
            update transactions
            set receipt_path = coalesce(?, receipt_path)
            where id = ? and user_id = ?
            """,
            (receipt_path, transaction_id, user_id),
        )


def delete_transaction(transaction_id, user_id):
    with db() as conn:
        transaction = conn.execute(
            "select fixed_bill_id from transactions where id = ? and user_id = ?",
            (transaction_id, user_id),
        ).fetchone()
        if transaction and transaction["fixed_bill_id"]:
            conn.execute(
                "update fixed_bills set status = 'pendente' where id = ? and user_id = ?",
                (transaction["fixed_bill_id"], user_id),
            )
        if transaction and "revenue_id" in transaction.keys() and transaction["revenue_id"]:
            conn.execute(
                "update revenues set status = 'prevista', received_date = null where id = ? and user_id = ?",
                (transaction["revenue_id"], user_id),
            )
        conn.execute("delete from transactions where id = ? and user_id = ?", (transaction_id, user_id))


def duplicate_transaction(transaction_id, user_id, month=None, year=None):
    original = get_transaction(transaction_id, user_id)
    if not original:
        return None
    with db() as conn:
        cursor = conn.execute(
            """
            insert into transactions
              (user_id, type, date, amount, category_id, description, payment_method, status, origin, fixed_bill_id, revenue_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                original["type"],
                selected_period_date(month, year),
                original["amount"],
                original["category_id"],
                original["description"],
                original["payment_method"],
                original["status"],
                original["origin"],
                original["fixed_bill_id"] if "fixed_bill_id" in original.keys() else None,
                original["revenue_id"] if "revenue_id" in original.keys() else None,
            ),
        )
        return cursor.lastrowid


def sync_fixed_bill_transaction(conn, bill, status=None):
    """Mantem contas fixas pagas conectadas ao extrato e ao Dashboard."""
    target_status = occurrence_status(status or bill["status"])
    occurrence_id = bill["occurrence_id"] if "occurrence_id" in bill.keys() else None
    transaction_id = bill["transaction_id"] if "transaction_id" in bill.keys() else None
    existing = None
    if transaction_id:
        existing = conn.execute("select id from transactions where id = ? and user_id = ?", (transaction_id, bill["user_id"])).fetchone()
    if not existing:
        month = month_prefix(bill["reference_month"], bill["reference_year"]) if "reference_month" in bill.keys() else current_month_prefix()
        existing = conn.execute(
            """
            select id from transactions
            where user_id = ?
              and fixed_bill_id = ?
              and date like ?
            order by id desc
            limit 1
            """,
            (bill["user_id"], bill["id"], f"{month}%"),
        ).fetchone()

    if target_status == "paid":
        transaction_date = bill["due_date"] if "due_date" in bill.keys() else current_month_transaction_date(bill["due_day"])
        amount = bill["amount"] if "amount" in bill.keys() else bill["expected_amount"]
        values = (
            "despesa",
            transaction_date,
            money(amount),
            bill["category_id"],
            bill["name"],
            "Pix",
            "pago",
            "conta_fixa",
            bill["id"],
            bill["user_id"],
        )
        if existing:
            conn.execute(
                """
                update transactions
                set type = ?, date = ?, amount = ?, category_id = ?, description = ?,
                    payment_method = ?, status = ?, origin = ?, fixed_bill_id = ?
                where id = ? and user_id = ?
                """,
                (*values[:-1], existing["id"], bill["user_id"]),
            )
            created_transaction_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                insert into transactions
                  (type, date, amount, category_id, description, payment_method, status, origin, fixed_bill_id, user_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            created_transaction_id = cursor.lastrowid
        if occurrence_id:
            conn.execute(
                """
                update fixed_bill_occurrences
                set transaction_id = ?, paid_at = coalesce(paid_at, date('now')), updated_at = current_timestamp
                where id = ? and user_id = ?
                """,
                (created_transaction_id, occurrence_id, bill["user_id"]),
            )
        return

    if existing and target_status in ("postponed", "canceled", "pending", "overdue"):
        conn.execute(
            "update transactions set status = ? where id = ? and user_id = ?",
            (legacy_bill_status(target_status), existing["id"], bill["user_id"]),
        )


def sync_all_paid_fixed_bills(user_id=None):
    params = []
    where = "where o.status = 'paid'"
    if user_id:
        where += " and o.user_id = ?"
        params.append(user_id)
    with db() as conn:
        bills = conn.execute(
            f"""
            select f.*, o.id as occurrence_id, o.reference_month, o.reference_year, o.due_date,
                   o.amount, o.status as occurrence_status, o.transaction_id, o.paid_at
            from fixed_bill_occurrences o
            join fixed_bills f on f.id = o.fixed_bill_id
            {where}
            """,
            params,
        ).fetchall()
        for bill in bills:
            sync_fixed_bill_transaction(conn, bill, "paid")


def _bill_priority(bill):
    today = date.today()
    if "due_date" in bill.keys() and bill["due_date"]:
        due_date = date.fromisoformat(bill["due_date"])
    else:
        due_day = min(int(bill["due_day"] or today.day), 28)
        due_date = today.replace(day=due_day)
    days_left = (due_date - today).days
    status = legacy_bill_status(bill["occurrence_status"]) if "occurrence_status" in bill.keys() else bill["status"]
    if status == "atrasado" or days_left < 0:
        return "atrasadas", "Atrasadas"
    if status == "adiado":
        return "adiadas", "Adiadas"
    if status == "pago":
        return "pagas", "Pagas"
    if days_left == 0:
        return "hoje", "Vencem hoje"
    if days_left <= 7:
        return "sete_dias", "Proximos 7 dias"
    return "trinta_dias", "Proximos 30 dias"


def _bill_row_payload(bill):
    data = dict(bill)
    if "occurrence_status" in data:
        data["status"] = legacy_bill_status(data["occurrence_status"])
        data["expected_amount"] = data.get("amount", data.get("expected_amount"))
        if data.get("due_date"):
            data["due_day"] = date.fromisoformat(data["due_date"]).day
    priority_key, priority_label = _bill_priority(bill)
    data["priority_key"] = priority_key
    data["priority_label"] = priority_label
    data["default_amount"] = data.get("default_amount") or data.get("expected_amount") or 0
    data["payment_method"] = data.get("payment_method") or "boleto"
    data["recurrence_interval"] = data.get("recurrence_interval") or data.get("recurrence") or "mensal"
    data["recurrence_type"] = data.get("recurrence_type") or data.get("recurrence") or "mensal"
    data["ask_value_before_generate"] = 1 if truthy(data.get("ask_value_before_generate")) else 0
    data["auto_update_default_value"] = 1 if truthy(data.get("auto_update_default_value")) else 0
    data["is_installment"] = 1 if truthy(data.get("is_installment")) or truthy(data.get("is_installment_occurrence")) else 0
    data["installment_label"] = (
        f"{data.get('installment_number')}/{data.get('total_installments')}"
        if data.get("installment_number") and data.get("total_installments")
        else None
    )
    return data


def list_fixed_bills(user_id, search=None, category_id=None, status=None, due=None, recurrence=None, month=None, year=None, recurring=False):
    selected_month, selected_year = selected_month_year(month, year)
    if not recurring:
        generate_monthly_fixed_bill_occurrences(user_id, selected_month, selected_year)
    params = [user_id]
    search_sql = ""
    if search:
        search_sql = " and lower(f.name) like lower(?)"
        params.append(f"%{search}%")
    category_sql = ""
    if category_id:
        category_sql = " and f.category_id = ?"
        params.append(category_id)
    status_sql = ""
    if status:
        status_sql = " and lower(o.status) = lower(?)"
        params.append(occurrence_status(status))
    recurrence_sql = ""
    if recurrence:
        recurrence_sql = " and lower(coalesce(f.recurrence_interval, f.recurrence)) = lower(?)"
        params.append(recurrence)
    due_sql = ""
    if due:
        today = date.today()
        if due == "hoje":
            due_sql = " and cast(strftime('%d', o.due_date) as integer) = ?"
            params.append(today.day)
        elif due == "7":
            due_sql = " and cast(strftime('%d', o.due_date) as integer) between ? and ?"
            params.extend([today.day, min(today.day + 7, 31)])
        elif due == "30":
            due_sql = " and cast(strftime('%d', o.due_date) as integer) between ? and ?"
            params.extend([today.day, min(today.day + 30, 31)])

    with db() as conn:
        if recurring:
            rows = conn.execute(
                """
                select f.*, c.name as category_name
                from fixed_bills f
                left join categories c on c.id = f.category_id
                where f.user_id = ?""" + search_sql + category_sql + recurrence_sql + """
                order by f.due_day asc
                """,
                params,
            ).fetchall()
        else:
            params.extend([selected_month, selected_year])
            rows = conn.execute(
                """
                select
                  f.id,
                  f.user_id,
                  f.name,
                  f.category_id,
                  f.expected_amount,
                  f.default_amount,
                  f.due_day,
                  f.recurrence,
                  f.recurrence_type,
                  f.recurrence_interval,
                  f.start_date,
                  f.payment_method,
                  f.alert_days_before,
                  f.ask_value_before_generate,
                  f.auto_update_default_value,
                  f.is_installment,
                  f.total_installments,
                  f.installment_amount,
                  f.paid_installments,
                  f.installment_start_date,
                  f.installment_total_amount,
                  f.notes as bill_notes,
                  f.active,
                  o.id as occurrence_id,
                  o.reference_month,
                  o.reference_year,
                  o.due_date,
                  o.amount,
                  o.status as occurrence_status,
                  o.paid_at,
                  o.postponed_to_month,
                  o.postponed_to_year,
                  o.transaction_id,
                  o.notes,
                  o.installment_number,
                  o.total_installments as occurrence_total_installments,
                  o.is_installment_occurrence,
                  o.was_value_confirmed,
                  o.original_default_amount,
                  c.name as category_name
                from fixed_bill_occurrences o
                join fixed_bills f on f.id = o.fixed_bill_id
                left join categories c on c.id = f.category_id
                where o.user_id = ?""" + search_sql + category_sql + status_sql + recurrence_sql + due_sql + """
                  and o.reference_month = ?
                  and o.reference_year = ?
                order by o.due_date asc
                """,
                params,
            ).fetchall()
    return [_bill_row_payload(row) for row in rows]


def summarize_fixed_bills(bills):
    total = sum(money(b["expected_amount"]) for b in bills if b["status"] not in ("cancelado",))
    counts = {status: len([b for b in bills if b["status"] == status]) for status in ["pago", "pendente", "atrasado", "adiado", "cancelado"]}
    active_bills = [b for b in bills if b["status"] in ("pendente", "atrasado")]
    next_bill = sorted(active_bills, key=lambda item: item["due_day"] or 99)[0] if active_bills else None
    categories = {}
    for bill in bills:
        name = bill["category_name"] or "Outros"
        categories[name] = categories.get(name, 0) + money(bill["expected_amount"])
    category_bars = [
        {"name": name, "total": value, "percent": round((value / total) * 100) if total else 0}
        for name, value in sorted(categories.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "total_mensal": total,
        "contas_pagas": counts["pago"],
        "contas_pendentes": counts["pendente"],
        "contas_atrasadas": counts["atrasado"],
        "contas_adiadas": counts["adiado"],
        "contas_canceladas": counts["cancelado"],
        "proximo_vencimento": next_bill["name"] if next_bill else "Nenhum",
        "proximo_valor": money(next_bill["expected_amount"]) if next_bill else 0,
        "category_bars": category_bars[:6],
    }


def get_fixed_bills_data(user_id):
    bills = list_fixed_bills(user_id)
    return summarize_fixed_bills(bills)


def create_fixed_bill(form, user_id, month=None, year=None):
    payload = fixed_bill_form_payload(form, month, year)
    with db() as conn:
        cursor = conn.execute(
            """
            insert into fixed_bills
              (user_id, name, expected_amount, default_amount, due_day, category_id, status, recurrence,
               recurrence_type, recurrence_interval, start_date, payment_method, alert_days_before,
               ask_value_before_generate, auto_update_default_value, is_installment, total_installments,
               installment_amount, paid_installments, installment_start_date, installment_total_amount,
               active, notes)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload["expected_amount"],
                payload["default_amount"],
                payload["due_day"],
                payload["category_id"],
                payload["status"],
                payload["recurrence"],
                payload["recurrence_type"],
                payload["recurrence_interval"],
                payload["start_date"],
                payload["payment_method"],
                payload["alert_days_before"],
                payload["ask_value_before_generate"],
                payload["auto_update_default_value"],
                payload["is_installment"],
                payload["total_installments"],
                payload["installment_amount"],
                payload["paid_installments"],
                payload["installment_start_date"],
                payload["installment_total_amount"],
                payload["active"],
                payload["notes"],
            ),
        )
        month, year = selected_month_year(month, year)
        due_day = min(int(payload["due_day"] or 1), 28)
        due_date = date(year, month, due_day).isoformat()
        installment_number = None
        total_installments = None
        occurrence_notes = None
        if payload["is_installment"]:
            start_date = date.fromisoformat((payload["installment_start_date"] or payload["start_date"])[:10])
            installment_number = (year - start_date.year) * 12 + (month - start_date.month) + 1
            total_installments = payload["total_installments"]
            occurrence_notes = f"Parcela {installment_number}/{total_installments}"
        conn.execute(
            """
            insert or ignore into fixed_bill_occurrences
              (fixed_bill_id, user_id, reference_month, reference_year, due_date, amount, status,
               installment_number, total_installments, is_installment_occurrence, original_default_amount, notes)
            values (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                cursor.lastrowid,
                user_id,
                month,
                year,
                due_date,
                payload["expected_amount"],
                installment_number,
                total_installments,
                payload["is_installment"],
                payload["default_amount"],
                occurrence_notes,
            ),
        )
        occurrence = conn.execute(
            """
            select f.*, o.id as occurrence_id, o.reference_month, o.reference_year, o.due_date,
                   o.amount, o.status as occurrence_status, o.transaction_id, o.paid_at,
                   o.installment_number, o.total_installments as occurrence_total_installments,
                   o.is_installment_occurrence
            from fixed_bill_occurrences o
            join fixed_bills f on f.id = o.fixed_bill_id
            where o.fixed_bill_id = ? and o.user_id = ? and o.reference_month = ? and o.reference_year = ?
            """,
            (cursor.lastrowid, user_id, month, year),
        ).fetchone()
        if occurrence:
            sync_fixed_bill_transaction(conn, occurrence, occurrence["occurrence_status"])
        return cursor.lastrowid


def get_fixed_bill(bill_id, user_id, month=None, year=None):
    month, year = selected_month_year(month, year)
    generate_monthly_fixed_bill_occurrences(user_id, month, year)
    with db() as conn:
        row = conn.execute(
            """
            select
              f.id,
              f.user_id,
              f.name,
              f.category_id,
              f.expected_amount,
              f.default_amount,
              f.due_day,
              f.recurrence,
              f.recurrence_type,
              f.recurrence_interval,
              f.start_date,
              f.payment_method,
              f.alert_days_before,
              f.ask_value_before_generate,
              f.auto_update_default_value,
              f.is_installment,
              f.total_installments,
              f.installment_amount,
              f.paid_installments,
              f.installment_start_date,
              f.installment_total_amount,
              f.notes as bill_notes,
              f.active,
              o.id as occurrence_id,
              o.reference_month,
              o.reference_year,
              o.due_date,
              o.amount,
              o.status as occurrence_status,
              o.paid_at,
              o.postponed_to_month,
              o.postponed_to_year,
              o.transaction_id,
              o.notes,
              o.installment_number,
              o.total_installments as occurrence_total_installments,
              o.is_installment_occurrence,
              o.was_value_confirmed,
              o.original_default_amount,
              c.name as category_name
            from fixed_bill_occurrences o
            join fixed_bills f on f.id = o.fixed_bill_id
            left join categories c on c.id = f.category_id
            where f.id = ? and o.user_id = ? and o.reference_month = ? and o.reference_year = ?
            """,
            (bill_id, user_id, month, year),
        ).fetchone()
    return _bill_row_payload(row) if row else None


def update_fixed_bill(bill_id, form, user_id, month=None, year=None):
    month, year = selected_month_year(month, year)
    generate_monthly_fixed_bill_occurrences(user_id, month, year)
    payload = fixed_bill_form_payload(form, month, year)
    with db() as conn:
        conn.execute(
            """
            update fixed_bills
            set name = ?,
                expected_amount = ?,
                default_amount = ?,
                due_day = ?,
                category_id = ?,
                status = ?,
                recurrence = ?,
                recurrence_type = ?,
                recurrence_interval = ?,
                start_date = ?,
                payment_method = ?,
                alert_days_before = ?,
                ask_value_before_generate = ?,
                auto_update_default_value = ?,
                is_installment = ?,
                total_installments = ?,
                installment_amount = ?,
                paid_installments = ?,
                installment_start_date = ?,
                installment_total_amount = ?,
                active = ?,
                notes = ?,
                updated_at = current_timestamp
            where id = ? and user_id = ?
            """,
            (
                payload["name"],
                payload["expected_amount"],
                payload["default_amount"],
                payload["due_day"],
                payload["category_id"],
                payload["status"],
                payload["recurrence"],
                payload["recurrence_type"],
                payload["recurrence_interval"],
                payload["start_date"],
                payload["payment_method"],
                payload["alert_days_before"],
                payload["ask_value_before_generate"],
                payload["auto_update_default_value"],
                payload["is_installment"],
                payload["total_installments"],
                payload["installment_amount"],
                payload["paid_installments"],
                payload["installment_start_date"],
                payload["installment_total_amount"],
                payload["active"],
                payload["notes"],
                bill_id,
                user_id,
            ),
        )
        due_day = min(int(payload["due_day"] or 1), 28)
        installment_number = None
        total_installments = None
        occurrence_notes = None
        if payload["is_installment"]:
            start_date = date.fromisoformat((payload["installment_start_date"] or payload["start_date"])[:10])
            installment_number = (year - start_date.year) * 12 + (month - start_date.month) + 1
            total_installments = payload["total_installments"]
            occurrence_notes = f"Parcela {installment_number}/{total_installments}"
        conn.execute(
            """
            update fixed_bill_occurrences
            set due_date = ?,
                amount = ?,
                installment_number = ?,
                total_installments = ?,
                is_installment_occurrence = ?,
                original_default_amount = ?,
                notes = coalesce(?, notes),
                updated_at = current_timestamp
            where fixed_bill_id = ? and user_id = ? and reference_month = ? and reference_year = ?
            """,
            (
                date(year, month, due_day).isoformat(),
                payload["expected_amount"],
                installment_number,
                total_installments,
                payload["is_installment"],
                payload["default_amount"],
                occurrence_notes,
                bill_id,
                user_id,
                month,
                year,
            ),
        )
        occurrence = conn.execute(
            """
            select f.*, o.id as occurrence_id, o.reference_month, o.reference_year, o.due_date,
                   o.amount, o.status as occurrence_status, o.transaction_id, o.paid_at,
                   o.installment_number, o.total_installments as occurrence_total_installments,
                   o.is_installment_occurrence
            from fixed_bill_occurrences o
            join fixed_bills f on f.id = o.fixed_bill_id
            where o.fixed_bill_id = ? and o.user_id = ? and o.reference_month = ? and o.reference_year = ?
            """,
            (bill_id, user_id, month, year),
        ).fetchone()
        if occurrence:
            sync_fixed_bill_transaction(conn, occurrence, occurrence["occurrence_status"])


def delete_fixed_bill(bill_id, user_id):
    with db() as conn:
        conn.execute(
            """
            update transactions
            set fixed_bill_id = null
            where fixed_bill_id = ? and user_id = ?
            """,
            (bill_id, user_id),
        )
        conn.execute(
            "delete from fixed_bill_occurrences where fixed_bill_id = ? and user_id = ?",
            (bill_id, user_id),
        )
        conn.execute("delete from fixed_bills where id = ? and user_id = ?", (bill_id, user_id))


def update_bill_status(bill_id, status, user_id, month=None, year=None):
    month, year = selected_month_year(month, year)
    generate_monthly_fixed_bill_occurrences(user_id, month, year)
    with db() as conn:
        target_status = occurrence_status(status)
        paid_at = date.today().isoformat() if target_status == "paid" else None
        conn.execute(
            """
            update fixed_bill_occurrences
            set status = ?, paid_at = coalesce(?, paid_at), updated_at = current_timestamp
            where fixed_bill_id = ? and user_id = ? and reference_month = ? and reference_year = ?
            """,
            (target_status, paid_at, bill_id, user_id, month, year),
        )
        occurrence = conn.execute(
            """
            select f.*, o.id as occurrence_id, o.reference_month, o.reference_year, o.due_date,
                   o.amount, o.status as occurrence_status, o.transaction_id, o.paid_at,
                   o.installment_number, o.total_installments as occurrence_total_installments,
                   o.is_installment_occurrence
            from fixed_bill_occurrences o
            join fixed_bills f on f.id = o.fixed_bill_id
            where o.fixed_bill_id = ? and o.user_id = ? and o.reference_month = ? and o.reference_year = ?
            """,
            (bill_id, user_id, month, year),
        ).fetchone()
        if occurrence:
            sync_fixed_bill_transaction(conn, occurrence, target_status)
            if target_status == "paid" and truthy(occurrence["is_installment"] if "is_installment" in occurrence.keys() else 0):
                conn.execute(
                    """
                    update fixed_bills
                    set paid_installments = max(coalesce(paid_installments, 0), coalesce(?, 0)),
                        active = case
                          when coalesce(?, 0) >= coalesce(total_installments, 0) then 0
                          else active
                        end,
                        updated_at = current_timestamp
                    where id = ? and user_id = ?
                    """,
                    (occurrence["installment_number"], occurrence["installment_number"], bill_id, user_id),
                )
            if target_status == "postponed":
                next_month = month + 1
                next_year = year
                if next_month == 13:
                    next_month = 1
                    next_year += 1
                due_day = min(int(occurrence["due_day"] or 1), 28)
                conn.execute(
                    """
                    insert or ignore into fixed_bill_occurrences
                      (fixed_bill_id, user_id, reference_month, reference_year, due_date, amount, status, notes)
                    values (?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        bill_id,
                        user_id,
                        next_month,
                        next_year,
                        date(next_year, next_month, due_day).isoformat(),
                        occurrence["amount"],
                        f"Adiada de {month:02d}/{year}",
                    ),
                )
                conn.execute(
                    """
                    update fixed_bill_occurrences
                    set postponed_to_month = ?, postponed_to_year = ?
                    where id = ? and user_id = ?
                    """,
                    (next_month, next_year, occurrence["occurrence_id"], user_id),
                )


def create_financial_attachment(user_id, linked_type, linked_id, metadata):
    allowed_types = {"transaction", "revenue", "fixed_bill_occurrence"}
    if linked_type not in allowed_types:
        raise ValueError("Tipo de vinculo de anexo invalido")
    with db() as conn:
        cursor = conn.execute(
            """
            insert into financial_attachments
              (user_id, linked_type, linked_id, original_file_name, stored_file_name,
               file_path, file_type, file_size, source, gemini_extracted_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                linked_type,
                linked_id,
                metadata["original_file_name"],
                metadata["stored_file_name"],
                metadata["file_path"],
                metadata.get("file_type"),
                int(metadata.get("file_size") or 0),
                metadata.get("source") or "manual_upload",
                metadata.get("gemini_extracted_json"),
            ),
        )
        return cursor.lastrowid


def list_financial_attachments(user_id, linked_type=None, linked_id=None):
    clauses = ["user_id = ?"]
    params = [user_id]
    if linked_type:
        clauses.append("linked_type = ?")
        params.append(linked_type)
    if linked_id:
        clauses.append("linked_id = ?")
        params.append(linked_id)
    with db() as conn:
        return conn.execute(
            f"""
            select *
            from financial_attachments
            where {' and '.join(clauses)}
            order by created_at desc
            """,
            params,
        ).fetchall()


REVENUE_CATEGORIES = [
    "Salario",
    "Beneficios",
    "PLR",
    "Bonus",
    "Aluguel residencial",
    "Aluguel comercial",
    "Dividendos",
    "Juros",
    "Rendimentos",
    "Fundos",
    "Freelance",
    "Consultoria",
    "Reembolso",
    "Pix recebido",
    "Venda de item",
    "Outros",
]

REVENUE_STATUS = ["prevista", "recebida", "atrasada", "cancelada"]
REVENUE_RECURRENCES = ["mensal", "quinzenal", "semanal", "anual", "pontual"]
REVENUE_TYPES = ["pontual", "recorrente"]
CATEGORY_TYPES = ["receita", "despesa", "conta_fixa", "geral"]


def revenue_form_payload(form, month=None, year=None):
    expected_date = form.get("expected_date") or selected_period_date(month, year)
    expected_amount = float(form.get("expected_amount") or 0)
    if expected_amount < 0:
        raise ValueError("Valor previsto nao pode ser negativo")
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("Nome da receita e obrigatorio")
    if not form.get("category"):
        raise ValueError("Categoria e obrigatoria")

    is_recurring = truthy(form.get("is_recurring")) or form.get("type") == "recorrente"
    recurrence_interval = form.get("recurrence_interval") or form.get("recurrence") or ("mensal" if is_recurring else "pontual")
    recurrence_day = int(form.get("recurrence_day") or date.fromisoformat(expected_date).day)
    recurrence_start_date = form.get("recurrence_start_date") or expected_date
    received_date = form.get("received_date") or (expected_date if form.get("status") == "recebida" else None)
    base_date = date.fromisoformat(expected_date)
    next_expected_date = form.get("next_expected_date") or (next_recurrence_date(base_date, recurrence_interval).isoformat() if is_recurring else None)

    return {
        "name": name,
        "category": form.get("category") or "Outros",
        "expected_amount": expected_amount,
        "expected_date": expected_date,
        "received_date": received_date,
        "type": "recorrente" if is_recurring else form.get("type", "pontual"),
        "status": form.get("status", "prevista"),
        "recurrence": recurrence_interval if is_recurring else "pontual",
        "is_recurring": 1 if is_recurring else 0,
        "recurrence_interval": recurrence_interval,
        "recurrence_day": min(max(recurrence_day, 1), 28),
        "recurrence_start_date": recurrence_start_date,
        "ask_value_before_generate": 1 if truthy(form.get("ask_value_before_generate")) else 0,
        "auto_update_default_value": 1 if truthy(form.get("auto_update_default_value")) else 0,
        "default_amount": float(form.get("default_amount") or expected_amount),
        "next_expected_date": next_expected_date,
        "last_generated_date": form.get("last_generated_date") or None,
        "notify_day_before": 1 if truthy(form.get("notify_day_before", "1")) else 0,
        "notify_due_day": 1 if truthy(form.get("notify_due_day", "1")) else 0,
        "notify_overdue": 1 if truthy(form.get("notify_overdue", "1")) else 0,
        "notify_registered": 1 if truthy(form.get("notify_registered", "1")) else 0,
        "notes": form.get("notes"),
    }


def _normalize_revenue_status(revenue):
    if revenue["status"] == "prevista" and revenue["expected_date"] < date.today().isoformat():
        return "atrasada"
    return revenue["status"]


def _revenue_payload(row):
    data = dict(row)
    data["status"] = _normalize_revenue_status(row)
    return data


def sync_revenue_transaction(conn, revenue, status=None):
    target_status = status or _normalize_revenue_status(revenue)
    existing = conn.execute(
        "select id from transactions where user_id = ? and revenue_id = ? order by id desc limit 1",
        (revenue["user_id"], revenue["id"]),
    ).fetchone()

    if target_status == "recebida":
        received_date = revenue["received_date"] or date.today().isoformat()
        values = (
            "receita",
            received_date,
            money(revenue["expected_amount"]),
            None,
            revenue["name"],
            "Pix",
            "pago",
            "receita",
            revenue["id"],
            revenue["user_id"],
        )
        if existing:
            conn.execute(
                """
                update transactions
                set type = ?, date = ?, amount = ?, category_id = ?, description = ?,
                    payment_method = ?, status = ?, origin = ?, revenue_id = ?
                where id = ? and user_id = ?
                """,
                (*values[:-1], existing["id"], revenue["user_id"]),
            )
        else:
            conn.execute(
                """
                insert into transactions
                  (type, date, amount, category_id, description, payment_method, status, origin, revenue_id, user_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return

    if existing and target_status in ("prevista", "atrasada", "cancelada"):
        conn.execute(
            "update transactions set status = ? where id = ? and user_id = ?",
            ("cancelado" if target_status == "cancelada" else "pendente", existing["id"], revenue["user_id"]),
        )


def list_revenues(user_id, search=None, category=None, status=None, expected_period=None, received_period=None, type=None, month=None, year=None):
    params = [user_id]
    where = ""
    if search:
        where += " and lower(name) like lower(?)"
        params.append(f"%{search}%")
    if category:
        where += " and lower(category) = lower(?)"
        params.append(category)
    if status:
        where += " and lower(status) = lower(?)"
        params.append(status)
    if expected_period:
        where += " and expected_date >= date('now', ?)"
        params.append(f"-{int(expected_period)} days")
    elif month or year:
        where += " and expected_date like ?"
        params.append(f"{month_prefix(month, year)}%")
    if received_period:
        where += " and received_date >= date('now', ?)"
        params.append(f"-{int(received_period)} days")
    if type:
        where += " and lower(type) = lower(?)"
        params.append(type)

    with db() as conn:
        rows = conn.execute(
            f"""
            select *
            from revenues
            where user_id = ?{where}
            order by expected_date desc, id desc
            """,
            params,
        ).fetchall()
    return [_revenue_payload(row) for row in rows]


def summarize_revenues(revenues, month=None, year=None):
    month = month_prefix(month, year)
    month_items = [r for r in revenues if (r["expected_date"] or "").startswith(month) or (r["received_date"] or "").startswith(month)]
    received = [r for r in month_items if r["status"] == "recebida"]
    planned = [r for r in month_items if r["status"] in ("prevista", "atrasada", "recebida")]
    pending = [r for r in month_items if r["status"] in ("prevista", "atrasada")]
    next_revenue = sorted(pending, key=lambda item: item["expected_date"] or "9999-99-99")[0] if pending else None

    categories = {}
    for item in month_items:
        categories[item["category"]] = categories.get(item["category"], 0) + money(item["expected_amount"])
    total_planned = sum(money(r["expected_amount"]) for r in planned)

    category_bars = [
        {"name": name, "total": value, "percent": round((value / total_planned) * 100) if total_planned else 0}
        for name, value in sorted(categories.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "receitas_mes": sum(money(r["expected_amount"]) for r in received),
        "receitas_previstas": total_planned,
        "receitas_recebidas": sum(money(r["expected_amount"]) for r in received),
        "receitas_pendentes": sum(money(r["expected_amount"]) for r in pending),
        "receitas_atrasadas": len([r for r in month_items if r["status"] == "atrasada"]),
        "proximo_nome": next_revenue["name"] if next_revenue else "Nenhum",
        "proximo_data": next_revenue["expected_date"] if next_revenue else "-",
        "proximo_valor": money(next_revenue["expected_amount"]) if next_revenue else 0,
        "category_bars": category_bars[:6],
        "percentual_recebido": round((sum(money(r["expected_amount"]) for r in received) / total_planned) * 100) if total_planned else 0,
    }


def list_alerts(user_id, month=None, year=None):
    month, year = selected_month_year(month, year)
    with db() as conn:
        return conn.execute(
            """
            select *
            from alerts
            where (user_id = ? or user_id is null)
              and coalesce(reference_month, cast(strftime('%m', coalesce(scheduled_for, created_at)) as integer)) = ?
              and coalesce(reference_year, cast(strftime('%Y', coalesce(scheduled_for, created_at)) as integer)) = ?
            order by coalesce(scheduled_for, created_at) desc, id desc
            """,
            (user_id, month, year),
        ).fetchall()


def create_revenue(form, user_id, month=None, year=None):
    payload = revenue_form_payload(form, month, year)
    with db() as conn:
        duplicate = conn.execute(
            """
            select id from revenues
            where user_id = ?
              and lower(name) = lower(?)
              and expected_date like ?
            limit 1
            """,
            (user_id, payload["name"], f"{payload['expected_date'][:7]}%"),
        ).fetchone()
        if duplicate and not form.get("id"):
            raise ValueError("Ja existe uma receita com este nome na mesma competencia")
        cursor = conn.execute(
            """
            insert into revenues
              (user_id, name, category, expected_amount, expected_date, received_date, type, status, recurrence,
               is_recurring, recurrence_interval, recurrence_day, recurrence_start_date,
               ask_value_before_generate, auto_update_default_value, default_amount, next_expected_date,
               last_generated_date, notify_day_before, notify_due_day, notify_overdue, notify_registered, notes)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload["category"],
                payload["expected_amount"],
                payload["expected_date"],
                payload["received_date"],
                payload["type"],
                payload["status"],
                payload["recurrence"],
                payload["is_recurring"],
                payload["recurrence_interval"],
                payload["recurrence_day"],
                payload["recurrence_start_date"],
                payload["ask_value_before_generate"],
                payload["auto_update_default_value"],
                payload["default_amount"],
                payload["next_expected_date"],
                payload["last_generated_date"],
                payload["notify_day_before"],
                payload["notify_due_day"],
                payload["notify_overdue"],
                payload["notify_registered"],
                payload["notes"],
            ),
        )
        revenue = conn.execute("select * from revenues where id = ? and user_id = ?", (cursor.lastrowid, user_id)).fetchone()
        if revenue:
            sync_revenue_transaction(conn, revenue, revenue["status"])
        return cursor.lastrowid


def get_revenue(revenue_id, user_id):
    with db() as conn:
        row = conn.execute("select * from revenues where id = ? and user_id = ?", (revenue_id, user_id)).fetchone()
    return _revenue_payload(row) if row else None


def update_revenue(revenue_id, form, user_id):
    payload = revenue_form_payload(form)
    with db() as conn:
        conn.execute(
            """
            update revenues
            set name = ?, category = ?, expected_amount = ?, expected_date = ?, received_date = ?,
                type = ?, status = ?, recurrence = ?,
                is_recurring = ?, recurrence_interval = ?, recurrence_day = ?, recurrence_start_date = ?,
                ask_value_before_generate = ?, auto_update_default_value = ?, default_amount = ?,
                next_expected_date = ?, last_generated_date = ?,
                notify_day_before = ?, notify_due_day = ?, notify_overdue = ?, notify_registered = ?,
                notes = ?
            where id = ? and user_id = ?
            """,
            (
                payload["name"],
                payload["category"],
                payload["expected_amount"],
                payload["expected_date"],
                payload["received_date"],
                payload["type"],
                payload["status"],
                payload["recurrence"],
                payload["is_recurring"],
                payload["recurrence_interval"],
                payload["recurrence_day"],
                payload["recurrence_start_date"],
                payload["ask_value_before_generate"],
                payload["auto_update_default_value"],
                payload["default_amount"],
                payload["next_expected_date"],
                payload["last_generated_date"],
                payload["notify_day_before"],
                payload["notify_due_day"],
                payload["notify_overdue"],
                payload["notify_registered"],
                payload["notes"],
                revenue_id,
                user_id,
            ),
        )
        revenue = conn.execute("select * from revenues where id = ? and user_id = ?", (revenue_id, user_id)).fetchone()
        if revenue:
            sync_revenue_transaction(conn, revenue, revenue["status"])


def delete_revenue(revenue_id, user_id):
    with db() as conn:
        conn.execute("delete from transactions where revenue_id = ? and user_id = ?", (revenue_id, user_id))
        conn.execute("delete from revenues where id = ? and user_id = ?", (revenue_id, user_id))


def update_revenue_status(revenue_id, status, user_id):
    with db() as conn:
        if status == "recebida":
            conn.execute(
                """
                update revenues
                set status = ?,
                    received_date = coalesce(received_date, expected_date, date('now'))
                where id = ? and user_id = ?
                """,
                (status, revenue_id, user_id),
            )
        else:
            conn.execute("update revenues set status = ? where id = ? and user_id = ?", (status, revenue_id, user_id))
        revenue = conn.execute("select * from revenues where id = ? and user_id = ?", (revenue_id, user_id)).fetchone()
        if revenue:
            sync_revenue_transaction(conn, revenue, status)
    return get_revenue(revenue_id, user_id)


def generate_recurring_revenues(user_id, target_date=None):
    target_date = target_date or date.today()
    with db() as conn:
        templates = conn.execute(
            """
            select *
            from revenues
            where user_id = ?
              and is_recurring = 1
              and status != 'cancelada'
              and next_expected_date is not null
              and next_expected_date <= ?
            order by next_expected_date asc
            """,
            (user_id, target_date.isoformat()),
        ).fetchall()
        for template in templates:
            expected_date = template["next_expected_date"]
            exists = conn.execute(
                """
                select id from revenues
                where user_id = ?
                  and lower(name) = lower(?)
                  and expected_date = ?
                limit 1
                """,
                (user_id, template["name"], expected_date),
            ).fetchone()
            next_date = next_recurrence_date(date.fromisoformat(expected_date), template["recurrence_interval"]).isoformat()
            if not exists:
                conn.execute(
                    """
                    insert into revenues
                      (user_id, name, category, expected_amount, expected_date, received_date, type, status, recurrence,
                       is_recurring, recurrence_interval, recurrence_day, recurrence_start_date,
                       ask_value_before_generate, auto_update_default_value, default_amount, next_expected_date,
                       last_generated_date, notify_day_before, notify_due_day, notify_overdue, notify_registered, notes)
                    values (?, ?, ?, ?, ?, null, 'recorrente', 'prevista', ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        template["name"],
                        template["category"],
                        template["default_amount"] or template["expected_amount"],
                        expected_date,
                        template["recurrence"],
                        template["recurrence_interval"],
                        template["recurrence_day"],
                        template["recurrence_start_date"],
                        template["ask_value_before_generate"],
                        template["auto_update_default_value"],
                        template["default_amount"] or template["expected_amount"],
                        next_date,
                        expected_date,
                        template["notify_day_before"],
                        template["notify_due_day"],
                        template["notify_overdue"],
                        template["notify_registered"],
                        template["notes"],
                    ),
                )
                if template["ask_value_before_generate"]:
                    conn.execute(
                        """
                        insert into alerts (user_id, type, message, status, scheduled_for, reference_month, reference_year)
                        values (?, 'receita_recorrente', ?, 'pendente', ?, ?, ?)
                        """,
                        (
                            user_id,
                            f"Sua receita {template['name']} esta prevista para hoje. O valor continua R$ {float(template['default_amount'] or template['expected_amount']):.2f}?",
                            expected_date,
                            int(expected_date[5:7]),
                            int(expected_date[:4]),
                        ),
                    )
            conn.execute(
                """
                update revenues
                set next_expected_date = ?, last_generated_date = ?
                where id = ? and user_id = ?
                """,
                (next_date, expected_date, template["id"], user_id),
            )

        conn.execute(
            """
            update revenues
            set status = 'atrasada'
            where user_id = ?
              and status = 'prevista'
              and expected_date < ?
            """,
            (user_id, target_date.isoformat()),
        )


def normalize_category_type(value):
    value = (value or "geral").strip().lower()
    return value if value in CATEGORY_TYPES else "geral"


def category_payload(form):
    name = (form.get("name") or "").strip()
    if not name:
        raise ValueError("Nome da categoria e obrigatorio")
    color = (form.get("color") or "#38bdf8").strip()
    if not color.startswith("#") or len(color) not in (4, 7):
        raise ValueError("Cor deve estar em formato hexadecimal")
    icon = (form.get("icon") or name[:1] or "$").strip()[:3]
    return {
        "name": name,
        "color": color,
        "icon": icon,
        "type": normalize_category_type(form.get("type")),
        "monthly_limit": money(form.get("monthly_limit") or 0),
        "active": 1 if truthy(form.get("active", "1")) else 0,
    }


def list_categories(type=None, include_inactive=False, include_general=True):
    params = []
    clauses = []
    if not include_inactive:
        clauses.append("coalesce(active, 1) = 1")
    category_type = normalize_category_type(type) if type else None
    if category_type:
        if include_general and category_type != "geral":
            clauses.append("type in (?, 'geral')")
            params.append(category_type)
        else:
            clauses.append("type = ?")
            params.append(category_type)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    with db() as conn:
        return conn.execute(f"select * from categories {where} order by active desc, type, name", params).fetchall()


def list_revenue_category_names():
    names = [row["name"] for row in list_categories("receita", include_general=True)]
    for name in REVENUE_CATEGORIES:
        if name not in names:
            names.append(name)
    return names


def get_category(category_id):
    with db() as conn:
        return conn.execute("select * from categories where id = ?", (category_id,)).fetchone()


def create_category(form):
    payload = category_payload(form)
    with db() as conn:
        existing = conn.execute("select id from categories where lower(name) = lower(?)", (payload["name"],)).fetchone()
        if existing:
            raise ValueError("Ja existe uma categoria com este nome")
        cursor = conn.execute(
            """
            insert into categories (name, color, icon, type, monthly_limit, active)
            values (?, ?, ?, ?, ?, ?)
            """,
            (payload["name"], payload["color"], payload["icon"], payload["type"], payload["monthly_limit"], payload["active"]),
        )
        return conn.execute("select * from categories where id = ?", (cursor.lastrowid,)).fetchone()


def update_category(category_id, form):
    payload = category_payload(form)
    with db() as conn:
        current = conn.execute("select * from categories where id = ?", (category_id,)).fetchone()
        if not current:
            return None
        duplicate = conn.execute("select id from categories where lower(name) = lower(?) and id != ?", (payload["name"], category_id)).fetchone()
        if duplicate:
            raise ValueError("Ja existe uma categoria com este nome")
        old_name = current["name"]
        conn.execute(
            """
            update categories
            set name = ?, color = ?, icon = ?, type = ?, monthly_limit = ?, active = ?
            where id = ?
            """,
            (payload["name"], payload["color"], payload["icon"], payload["type"], payload["monthly_limit"], payload["active"], category_id),
        )
        if old_name != payload["name"]:
            conn.execute("update revenues set category = ? where lower(category) = lower(?)", (payload["name"], old_name))
        return conn.execute("select * from categories where id = ?", (category_id,)).fetchone()


def category_usage(category_id):
    category = get_category(category_id)
    if not category:
        return {"transactions": 0, "fixed_bills": 0, "revenues": 0, "total": 0}
    with db() as conn:
        transactions = conn.execute("select count(*) as total from transactions where category_id = ?", (category_id,)).fetchone()["total"]
        fixed_bills = conn.execute("select count(*) as total from fixed_bills where category_id = ?", (category_id,)).fetchone()["total"]
        revenues = conn.execute("select count(*) as total from revenues where lower(category) = lower(?)", (category["name"],)).fetchone()["total"]
    return {"transactions": transactions, "fixed_bills": fixed_bills, "revenues": revenues, "total": transactions + fixed_bills + revenues}


def deactivate_category(category_id):
    with db() as conn:
        conn.execute("update categories set active = 0 where id = ?", (category_id,))
        return conn.execute("select * from categories where id = ?", (category_id,)).fetchone()


def delete_category(category_id):
    usage = category_usage(category_id)
    if usage["total"]:
        raise ValueError("Categoria em uso. Desative em vez de excluir.")
    with db() as conn:
        conn.execute("delete from categories where id = ?", (category_id,))
    return True
