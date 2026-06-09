import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

from datetime import date

from app.database import db, init_db, seed_db
from app.services.finance_service import create_financial_attachment, create_revenue, update_bill_status
from app.services.report_service import (
    MONTH_NAMES,
    brl,
    get_monthly_report_data,
    generate_monthly_summary_text,
    send_report_to_telegram,
)
from app.services.goal_service import (
    add_goal_contribution,
    brl,
    create_goal,
    find_goal_by_text,
    list_goals,
    summarize_goals,
)
from ai.intent_parser import interpretar_mensagem
from ai.receipt_reader import ler_comprovante
from ai.response_generator import gerar_resposta_humanizada
from app.services.log_service import create_log
from app.services.telegram_link_service import UNLINKED_TELEGRAM_MESSAGE, link_telegram_account, resolve_telegram_user
from config.settings import settings


class TelegramNotLinked(Exception):
    pass


def initialize_runtime_db():
    init_db()
    if settings.SEED_DEMO_DATA:
        seed_db()


def ensure_telegram_user(telegram_id, first_name=None):
    if not telegram_id:
        return 1
    user_id = resolve_telegram_user(telegram_id)
    if not user_id:
        raise TelegramNotLinked(UNLINKED_TELEGRAM_MESSAGE)
    return user_id


def process_link_command(code, telegram_user):
    initialize_runtime_db()
    if not telegram_user:
        return "Nao consegui identificar sua conta do Telegram."
    create_log(
        "info",
        "telegram",
        "link_command_processing",
        "Processando /vincular antes de validar usuario vinculado",
        telegram_id=str(telegram_user.id),
        details={"code": (code or "").strip().upper()},
    )
    try:
        result = link_telegram_account(code, telegram_user)
    except ValueError as exc:
        create_log(
            "warning",
            "telegram",
            "link_command_error",
            str(exc),
            telegram_id=str(telegram_user.id),
            details={"code": (code or "").strip().upper()},
        )
        return str(exc)
    create_log(
        "info",
        "telegram",
        "telegram_linked",
        "Telegram vinculado com sucesso",
        user_id=result["user_id"],
        telegram_id=str(telegram_user.id),
        details={"username": getattr(telegram_user, "username", None), "first_name": getattr(telegram_user, "first_name", None)},
    )
    return "✅ Conta vinculada com sucesso ao Meu Gestor Financeiro IA."


def find_category_id(conn, name):
    if not name:
        return None

    category = conn.execute("select id from categories where lower(name) = lower(?)", (name,)).fetchone()
    return category["id"] if category else None


def normalize_intent_date(intent, original_text=""):
    """Evita que respostas da IA com data antiga fiquem fora do mes atual no Dashboard."""
    if intent.get("intent") != "create_transaction":
        return intent

    today = date.today()
    raw_date = intent.get("date")
    try:
        parsed = date.fromisoformat(raw_date) if raw_date else today
    except (TypeError, ValueError):
        parsed = today

    text = (original_text or "").lower()
    year_was_explicit = str(parsed.year) in text
    if parsed.year != today.year and not year_was_explicit:
        parsed = today

    intent["date"] = parsed.isoformat()
    return intent


def save_transaction_from_intent(intent, user_id):
    if intent.get("type") == "receita":
        create_revenue(
            {
                "name": intent.get("description") or "Receita via Telegram",
                "category": intent.get("category") or "Pix recebido",
                "expected_amount": float(intent.get("amount") or 0),
                "expected_date": intent.get("date") or date.today().isoformat(),
                "received_date": intent.get("date") or date.today().isoformat(),
                "type": "pontual",
                "status": "recebida",
                "recurrence": "pontual",
                "notes": "Criada pelo Telegram",
            },
            user_id,
        )
        return

    with db() as conn:
        conn.execute(
            """
            insert into transactions
              (user_id, type, date, amount, category_id, description, payment_method, status, origin)
            values (?, ?, ?, ?, ?, ?, ?, 'pago', 'telegram')
            """,
            (
                user_id,
                intent.get("type", "despesa"),
                intent.get("date"),
                float(intent.get("amount") or 0),
                find_category_id(conn, intent.get("category")),
                intent.get("description"),
                "Pix",
            ),
        )


def save_receipt_transaction(receipt_data, user_id):
    with db() as conn:
        cursor = conn.execute(
            """
            insert into transactions
              (user_id, type, date, amount, category_id, description, payment_method, status, origin)
            values (?, 'despesa', ?, ?, ?, ?, ?, 'pago', 'comprovante')
            """,
            (
                user_id,
                receipt_data.get("data"),
                float(receipt_data.get("valor") or 0),
                find_category_id(conn, receipt_data.get("categoria_provavel")),
                receipt_data.get("descricao") or receipt_data.get("favorecido"),
                receipt_data.get("tipo_pagamento", "Pix"),
            ),
        )
        return cursor.lastrowid


def normalize_report_text(text):
    normalized = unicodedata.normalize("NFKD", (text or "").lower().strip())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def parse_report_period(text):
    normalized = normalize_report_text(text)
    month = date.today().month
    year = date.today().year
    normalized_months = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    for name, number in normalized_months.items():
        if name in tokens:
            month = number
            break
    for token in tokens:
        if token.isdigit() and len(token) == 4:
            year = int(token)
    return month, year


def is_report_request(text):
    normalized = normalize_report_text(text)
    keywords = [
        "resumo",
        "relatorio",
        "fechamento",
        "como foi meu mes",
        "saldo previsto",
        "maiores despesas",
        "quanto gastei",
        "comparar",
    ]
    return any(keyword in normalized for keyword in keywords)


def report_format_from_text(text):
    normalized = normalize_report_text(text)
    if "pdf" in normalized:
        return "pdf"
    if "imagem" in normalized or "png" in normalized or "visual" in normalized:
        return "image"
    return "text"


def category_question_answer(text, report_data):
    normalized = normalize_report_text(text)
    if "quanto gastei" not in normalized:
        return None
    for item in report_data["categories"]:
        if normalize_report_text(item["name"]) in normalized:
            return f"Voce gastou {brl(item['total'])} em {item['name']} em {report_data['label']}."
    if report_data["categories"]:
        top = report_data["categories"][0]
        return f"Sua maior despesa foi {top['name']}: {brl(top['total'])} em {report_data['label']}."
    return "Nao encontrei despesas categorizadas para esse mes ainda."


def largest_expenses_answer(report_data):
    categories = report_data["categories"][:5]
    if not categories:
        return "Nao encontrei despesas para esse mes ainda."
    lines = [f"Maiores despesas de {report_data['label']}:"]
    lines.extend([f"{index}. {item['name']}: {brl(item['total'])}" for index, item in enumerate(categories, start=1)])
    return "\n".join(lines)


def process_report_command(text, telegram_user=None):
    if not is_report_request(text):
        return None
    initialize_runtime_db()
    telegram_id = str(telegram_user.id) if telegram_user else None
    user_id = ensure_telegram_user(telegram_id, telegram_user.first_name if telegram_user else None) if telegram_id else 1
    month, year = parse_report_period(text)
    report_data = get_monthly_report_data(user_id, month, year)
    normalized = normalize_report_text(text)
    create_log("info", "telegram", "report_requested", text, user_id=user_id, telegram_id=telegram_id, details={"month": month, "year": year})

    if not report_data["has_data"]:
        return {"type": "text", "text": "Nao encontrei movimentacoes para esse mes ainda."}
    if "maiores despesas" in normalized:
        return {"type": "text", "text": largest_expenses_answer(report_data)}
    category_answer = category_question_answer(text, report_data)
    if category_answer:
        return {"type": "text", "text": category_answer}
    if "saldo previsto" in normalized:
        return {"type": "text", "text": f"Seu saldo previsto em {report_data['label']} e {brl(report_data['summary']['saldo_previsto'])}."}
    return send_report_to_telegram(user_id, month, year, report_format_from_text(text))


def is_goal_request(text):
    normalized = normalize_report_text(text)
    return "meta" in normalized or "metas" in normalized or "juntar" in normalized or "guardar por mes" in normalized


def process_goal_command(text, telegram_user=None):
    if not is_goal_request(text):
        return None
    initialize_runtime_db()
    telegram_id = str(telegram_user.id) if telegram_user else None
    user_id = ensure_telegram_user(telegram_id, telegram_user.first_name if telegram_user else None) if telegram_id else 1
    normalized = normalize_report_text(text)
    amount = 0
    match = re.search(r"(\d+[,.]?\d*)", normalized)
    if match:
        amount = float(match.group(1).replace(",", "."))

    if "criar meta" in normalized or normalized.startswith("meta de"):
        name_match = re.search(r"meta(?: de)? ([a-z ]+?)(?: de| para|$)", normalized, re.IGNORECASE)
        name = (name_match.group(1).strip() if name_match else "Nova meta")
        goal_id = create_goal(
            {
                "name": name.title(),
                "description": "Criada pelo Telegram",
                "type": "Outros",
                "target_amount": amount or 1000,
                "current_amount": 0,
                "monthly_target_amount": 0,
                "start_date": date.today().isoformat(),
                "icon": name[:1].upper(),
                "color": "#8b5cf6",
                "status": "no_ritmo",
            },
            user_id,
        )
        return f"Meta criada: {name.title()} com objetivo de {brl(amount or 1000)}."

    if "adicionar" in normalized and amount:
        goal = find_goal_by_text(user_id, text)
        if not goal:
            return "Nao encontrei uma meta para adicionar esse valor. Crie uma meta primeiro."
        add_goal_contribution(goal["id"], user_id, amount, date.today().isoformat(), "telegram", None, "Contribuicao via Telegram")
        updated = find_goal_by_text(user_id, goal["name"])
        return (
            f"Valor adicionado na meta {goal['name']}.\n"
            f"Atual: {brl(updated['current_calculated'])}\n"
            f"Objetivo: {brl(updated['target_amount'])}\n"
            f"Progresso: {updated['percent']}%"
        )

    if "quanto falta" in normalized or "falta" in normalized:
        goal = find_goal_by_text(user_id, text)
        if not goal:
            return "Nao encontrei essa meta ainda."
        return (
            f"Meta {goal['name']}\n"
            f"Atual: {brl(goal['current_calculated'])}\n"
            f"Objetivo: {brl(goal['target_amount'])}\n"
            f"Progresso: {goal['percent']}%\n"
            f"Faltam: {brl(goal['missing_amount'])}\n"
            f"Previsao: {goal['estimated_completion_label']}."
        )

    if "quanto preciso" in normalized and amount:
        deadline_month = 12 if "dezembro" in normalized else date.today().month
        deadline = date(date.today().year, deadline_month, 1)
        months = max((deadline.year - date.today().year) * 12 + deadline.month - date.today().month, 1)
        return f"Para juntar {brl(amount)} ate {deadline.strftime('%b/%Y')}, guarde cerca de {brl(amount / months)} por mes."

    goals = list_goals(user_id)
    if not goals:
        return "Voce ainda nao tem metas cadastradas. Posso criar uma com: criar meta de viagem de 5000."
    summary = summarize_goals(user_id)
    lines = [
        "Resumo das suas metas:",
        f"Total acumulado: {brl(summary['total_current'])}",
        f"Progresso medio: {summary['average_percent']}%",
        "",
    ]
    for goal in goals[:5]:
        lines.append(f"{goal['name']}: {brl(goal['current_calculated'])} / {brl(goal['target_amount'])} ({goal['percent']}%)")
    return "\n".join(lines)


def attach_receipt_file_to_transaction(file_path, user_id, transaction_id, receipt_data=None):
    if not file_path or not os.path.exists(file_path):
        return None
    upload_dir = Path("app/static/uploads/attachments")
    upload_dir.mkdir(parents=True, exist_ok=True)
    source = Path(file_path)
    stored_name = f"telegram_{transaction_id}_{source.name}"
    destination = upload_dir / stored_name
    shutil.move(str(source), destination)
    extension = source.suffix.lower().lstrip(".")
    return create_financial_attachment(
        user_id,
        "transaction",
        transaction_id,
        {
            "original_file_name": source.name,
            "stored_file_name": stored_name,
            "file_path": f"uploads/attachments/{stored_name}",
            "file_type": "application/pdf" if extension == "pdf" else f"image/{extension or 'jpeg'}",
            "file_size": destination.stat().st_size,
            "source": "telegram",
            "gemini_extracted_json": json.dumps(receipt_data or {}, ensure_ascii=False),
        },
    )


def process_text_message(text, telegram_user=None):
    initialize_runtime_db()
    telegram_id = str(telegram_user.id) if telegram_user else None
    first_name = telegram_user.first_name if telegram_user else None
    user_id = ensure_telegram_user(telegram_id, first_name) if telegram_id else 1

    try:
        intent = normalize_intent_date(interpretar_mensagem(text), text)
        create_log(
            "info",
            "telegram",
            "message_received",
            text,
            user_id=user_id,
            telegram_id=telegram_id,
            details={"intent": intent},
        )

        if intent["intent"] == "create_transaction":
            save_transaction_from_intent(intent, user_id)
            event = "receita" if intent.get("type") == "receita" else "lancamento"
            create_log(
                "info",
                "database",
                "transaction_created",
                "Lancamento criado via Telegram",
                user_id=user_id,
                telegram_id=telegram_id,
                details=intent,
            )
            return gerar_resposta_humanizada(
                event,
                {"valor": intent.get("amount"), "categoria": intent.get("category"), "percentual_orcamento": 72},
                settings.ASSISTANT_TONE,
            )

        if intent["intent"] == "mark_bill_paid":
            with db() as conn:
                bill = conn.execute(
                    "select id from fixed_bills where user_id = ? and lower(name) like lower(?) order by due_day asc limit 1",
                    (user_id, f"%{intent.get('bill_name')}%"),
                ).fetchone()
            if bill:
                update_bill_status(bill["id"], "pago", user_id)
            create_log("info", "telegram", "bill_paid", "Conta marcada como paga", user_id=user_id, telegram_id=telegram_id, details=intent)
            return gerar_resposta_humanizada("conta_paga", {}, settings.ASSISTANT_TONE)

        if intent["intent"] == "postpone_bill":
            with db() as conn:
                bill = conn.execute(
                    "select id from fixed_bills where user_id = ? and lower(name) like lower(?) order by due_day asc limit 1",
                    (user_id, f"%{intent.get('bill_name')}%"),
                ).fetchone()
            if bill:
                update_bill_status(bill["id"], "adiado", user_id)
            create_log("info", "telegram", "bill_postponed", "Conta adiada", user_id=user_id, telegram_id=telegram_id, details=intent)
            return gerar_resposta_humanizada("conta_adiada", {"categoria": intent.get("bill_name")}, settings.ASSISTANT_TONE)

        if intent["intent"] == "list_due_bills":
            with db() as conn:
                bills = conn.execute(
                    "select name, expected_amount, due_day from fixed_bills where user_id = ? and status = 'pendente'",
                    (user_id,),
                ).fetchall()
            if not bills:
                return "Nenhuma conta pendente agora. Sua paz financeira agradece."
            return "\n".join([f"{b['name']} vence dia {b['due_day']} - R$ {b['expected_amount']:.2f}" for b in bills])

        return "Resumo do mes pronto no dashboard. O painel esta de olho nos numeros por voce."
    except Exception as error:
        create_log("error", "telegram", "message_error", str(error), user_id=user_id, telegram_id=telegram_id, details={"text": text})
        raise


def format_receipt_confirmation(data):
    return (
        "Encontrei esse pagamento:\n"
        f"Valor: R$ {float(data.get('valor') or 0):.2f}\n"
        f"Favorecido: {data.get('favorecido') or 'Nao identificado'}\n"
        f"Categoria sugerida: {data.get('categoria_provavel') or 'Outros'}\n"
        f"Data: {data.get('data') or 'Nao identificada'}\n\n"
        "Deseja confirmar esse lancamento?"
    )


def process_receipt_photo(file_path, telegram_user=None):
    initialize_runtime_db()
    telegram_id = str(telegram_user.id) if telegram_user else None
    user_id = ensure_telegram_user(telegram_id, telegram_user.first_name if telegram_user else None) if telegram_id else 1
    data = ler_comprovante(file_path)
    create_log("info", "gemini", "receipt_read", "Comprovante analisado", user_id=user_id, telegram_id=telegram_id, details=data)
    return format_receipt_confirmation(data), data, user_id
