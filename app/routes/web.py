from datetime import date
import os

import csv
from io import StringIO
from urllib.parse import urlencode

from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from app.models import ORIGINS, PAYMENT_METHODS, TRANSACTION_STATUS, TRANSACTION_TYPES
from app.services.admin_service import admin_kpis, create_user as admin_create_user, get_user, list_users, telegram_badge, toggle_user_status, update_user, user_details
from app.services.auth_service import admin_required, authenticate, current_user_id, is_admin, login_required
from app.services.finance_service import (
    create_financial_attachment,
    create_fixed_bill,
    create_category,
    create_revenue,
    create_transaction,
    deactivate_category,
    delete_category,
    delete_fixed_bill,
    delete_revenue,
    delete_transaction,
    dashboard_api_data,
    duplicate_transaction,
    get_dashboard_data,
    get_fixed_bill,
    get_category,
    get_fixed_bills_data,
    get_lancamentos_data,
    get_revenue,
    get_transaction,
    list_alerts,
    list_categories,
    list_revenue_category_names,
    list_fixed_bills,
    list_financial_attachments,
    list_revenues,
    list_transactions,
    set_transaction_receipt_path,
    summarize_fixed_bills,
    summarize_revenues,
    summarize_transactions,
    update_category,
    update_transaction,
    update_bill_status,
    update_fixed_bill,
    update_revenue,
    update_revenue_status,
)
from app.services.finance_service import CATEGORY_TYPES, REVENUE_RECURRENCES, REVENUE_STATUS, REVENUE_TYPES
from app.services.log_service import create_log, list_logs
from app.services.goal_service import (
    add_goal_contribution,
    create_goal,
    delete_goal,
    get_goal,
    goals_page_data,
    list_goals,
    list_goal_contributions,
    summarize_goals,
    update_goal,
    update_goal_status,
)
from app.services.report_service import (
    generate_monthly_report_pdf,
    generate_report_csv,
    generate_report_xlsx,
    get_monthly_report_data,
)
from app.services.telegram_link_service import generate_link_code, get_user_telegram_status, unlink_telegram_account

web_bp = Blueprint("web", __name__)

ALLOWED_RECEIPT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


def save_uploaded_attachment(file_field="receipt_file"):
    uploaded = request.files.get(file_field)
    if not uploaded or not uploaded.filename:
        return None
    extension = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
    if extension not in ALLOWED_RECEIPT_EXTENSIONS:
        raise ValueError("Comprovante deve ser imagem ou PDF")
    uploaded.stream.seek(0, os.SEEK_END)
    file_size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    if file_size > MAX_ATTACHMENT_BYTES:
        raise ValueError("Arquivo deve ter no maximo 8 MB")
    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "attachments")
    os.makedirs(upload_dir, exist_ok=True)
    filename = secure_filename(uploaded.filename)
    dated_name = f"{date.today().strftime('%Y%m%d')}_{os.urandom(4).hex()}_{filename}"
    uploaded.save(os.path.join(upload_dir, dated_name))
    return {
        "original_file_name": uploaded.filename,
        "stored_file_name": dated_name,
        "file_path": f"uploads/attachments/{dated_name}",
        "file_type": uploaded.mimetype or extension,
        "file_size": file_size,
        "source": "manual_upload",
    }


def attach_uploaded_file(user_id, linked_type, linked_id, file_field="receipt_file"):
    metadata = save_uploaded_attachment(file_field)
    if not metadata:
        return None
    return create_financial_attachment(user_id, linked_type, linked_id, metadata)

MONTH_NAMES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Marco",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


def normalize_period(month=None, year=None):
    today = date.today()
    try:
        month = int(month or today.month)
        year = int(year or today.year)
    except (TypeError, ValueError):
        month, year = today.month, today.year
    month = min(max(month, 1), 12)
    year = min(max(year, 2000), 2100)
    return month, year


def selected_period():
    month, year = normalize_period(session.get("selected_month"), session.get("selected_year"))
    return {"month": month, "year": year, "label": f"{MONTH_NAMES[month]} de {year}"}


def shift_period(month, year, delta):
    month = int(month) + delta
    year = int(year)
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return normalize_period(month, year)


def period_url(endpoint=None, month=None, year=None, **values):
    period = selected_period()
    args = request.args.to_dict(flat=True)
    args.update(values)
    args["month"] = month or period["month"]
    args["year"] = year or period["year"]
    args.pop("page", None)
    if endpoint:
        return url_for(endpoint, **args)
    query = urlencode(args)
    return f"{request.path}?{query}" if query else request.path


@web_bp.before_request
def persist_selected_period():
    if request.endpoint in {"web.login", "web.logout", "static"}:
        return
    month_arg = request.args.get("month")
    year_arg = request.args.get("year")
    if month_arg or year_arg:
        month, year = normalize_period(month_arg, year_arg)
        session["selected_month"] = month
        session["selected_year"] = year
    elif "selected_month" not in session or "selected_year" not in session:
        month, year = normalize_period()
        session["selected_month"] = month
        session["selected_year"] = year


@web_bp.app_context_processor
def inject_selected_period():
    period = selected_period()
    previous_month, previous_year = shift_period(period["month"], period["year"], -1)
    next_month, next_year = shift_period(period["month"], period["year"], 1)
    current_month, current_year = normalize_period()
    return {
        "selected_period": period,
        "period_months": MONTH_NAMES,
        "period_years": range(current_year - 5, current_year + 6),
        "previous_period_url": period_url(month=previous_month, year=previous_year),
        "next_period_url": period_url(month=next_month, year=next_year),
        "current_period_url": period_url(month=current_month, year=current_year),
        "period_url": period_url,
    }


def row_to_dict(row):
    return dict(row) if row else None


def transaction_payload(row):
    data = row_to_dict(row)
    if not data:
        return None
    data["hour"] = (data.get("created_at") or "")[11:16]
    return data


def transaction_filters_from_request():
    period = selected_period()
    return {
        "origin": request.args.get("origin") or None,
        "category_id": request.args.get("category_id") or None,
        "status": request.args.get("status") or None,
        "search": request.args.get("search") or None,
        "period": request.args.get("period") or None,
        "month": period["month"],
        "year": period["year"],
    }


def bill_filters_from_request():
    return {
        "search": request.args.get("search") or None,
        "category_id": request.args.get("category_id") or None,
        "status": request.args.get("status") or None,
        "due": request.args.get("due") or None,
        "recurrence": request.args.get("recurrence") or None,
    }


def fixed_bill_payload(row):
    return dict(row) if row else None


def revenue_filters_from_request():
    period = selected_period()
    return {
        "search": request.args.get("search") or None,
        "category": request.args.get("category") or None,
        "status": request.args.get("status") or None,
        "expected_period": request.args.get("expected_period") or None,
        "received_period": request.args.get("received_period") or None,
        "type": request.args.get("type") or None,
        "month": period["month"],
        "year": period["year"],
    }


def revenue_payload(row):
    return dict(row) if row else None


@web_bp.app_template_filter("brl")
def brl(value):
    value = float(value or 0)
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


@web_bp.route("/")
@web_bp.route("/dashboard")
@login_required
def dashboard():
    requested_user_id = request.args.get("user_id", type=int) or current_user_id()
    period = selected_period()
    if requested_user_id != current_user_id() and not is_admin():
        return redirect(url_for("web.dashboard"))

    data = get_dashboard_data(requested_user_id, month=period["month"], year=period["year"])
    goals_summary = summarize_goals(requested_user_id, month=period["month"], year=period["year"])
    if goals_summary["total_goals"]:
        data["goal_current"] = goals_summary["total_current"]
        data["goal_target"] = goals_summary["total_target"]
        data["goal_percent"] = goals_summary["average_percent"]
        data["goal_missing"] = max(goals_summary["total_target"] - goals_summary["total_current"], 0)

    create_log("info", "dashboard", "view_dashboard", "Dashboard carregado", user_id=requested_user_id)
    return render_template("dashboard.html", data=data, dashboard_user_id=requested_user_id)


@web_bp.route("/api/dashboard")
@login_required
def api_dashboard():
    requested_user_id = request.args.get("user_id", type=int) or current_user_id()
    period = selected_period()
    if requested_user_id != current_user_id() and not is_admin():
        return jsonify({"error": "Acesso negado"}), 403

    create_log("info", "dashboard", "api_dashboard", "Dashboard sincronizado", user_id=requested_user_id)
    return jsonify(dashboard_api_data(requested_user_id, month=period["month"], year=period["year"]))


@web_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        user = authenticate(request.form.get("email", ""), request.form.get("password", ""))
        if user:
            session.clear()
            session["user"] = user
            session.permanent = True
            return redirect(url_for("web.dashboard"))

        error = "Email ou senha invalidos."

    return render_template("login.html", error=error)


@web_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.login"))


@web_bp.route("/lancamentos", methods=["GET", "POST"])
@login_required
def lancamentos():
    active_period = selected_period()
    if request.method == "POST":
        try:
            create_transaction(request.form, current_user_id(), month=active_period["month"], year=active_period["year"])
        except ValueError as error:
            create_log("warning", "database", "transaction_validation_error", str(error), user_id=current_user_id())
        return redirect(url_for("web.lancamentos"))

    origin = request.args.get("origin") or None
    category_id = request.args.get("category_id") or None
    status = request.args.get("status") or None
    search = request.args.get("search") or None
    period_filter = request.args.get("period") or None
    per_page = request.args.get("per_page", 10, type=int)
    page = request.args.get("page", 1, type=int)
    per_page = per_page if per_page in [10, 25, 50] else 10

    transactions = list_transactions(
        current_user_id(),
        origin=origin,
        category_id=category_id,
        status=status,
        search=search,
        period=period_filter,
    )

    if request.args.get("export") == "csv":
        output = StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Data", "Hora", "Descricao", "Categoria", "Origem", "Forma pagamento", "Status", "Tipo", "Valor"])
        for item in transactions:
            writer.writerow(
                [
                    item["date"],
                    (item["created_at"] or "")[11:16],
                    item["description"],
                    item["category_name"] or "",
                    item["origin"],
                    item["payment_method"],
                    item["status"],
                    item["type"],
                    item["amount"],
                ]
            )
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=lancamentos.csv"},
        )

    total_records = len(transactions)
    total_pages = max((total_records + per_page - 1) // per_page, 1)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    paginated_transactions = transactions[start : start + per_page]

    return render_template(
        "lancamentos.html",
        transactions=paginated_transactions,
        summary=get_lancamentos_data(current_user_id(), month=active_period["month"], year=active_period["year"]),
        categories=list_categories(),
        today=date.today().isoformat(),
        statuses=TRANSACTION_STATUS,
        types=TRANSACTION_TYPES,
        origins=ORIGINS,
        payment_methods=PAYMENT_METHODS,
        selected_origin=origin or "",
        selected_category=category_id or "",
        selected_status=status or "",
        selected_days_period=period_filter or "",
        search=search or "",
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_records=total_records,
        start_record=start + 1 if total_records else 0,
        end_record=min(start + per_page, total_records),
    )


@web_bp.route("/receitas", methods=["GET", "POST"])
@login_required
def receitas():
    period = selected_period()
    if request.method == "POST":
        try:
            revenue_id = create_revenue(request.form, current_user_id(), month=period["month"], year=period["year"])
            if request.form.get("goal_id") and request.form.get("goal_amount"):
                add_goal_contribution(request.form.get("goal_id"), current_user_id(), request.form.get("goal_amount"), request.form.get("received_date") or request.form.get("expected_date"), "receita", revenue_id, "Parte da receita direcionada para meta")
        except ValueError as error:
            create_log("warning", "database", "revenue_validation_error", str(error), user_id=current_user_id())
        return redirect(url_for("web.receitas"))

    filters = revenue_filters_from_request()
    revenues = list_revenues(current_user_id(), **filters)
    if request.args.get("export") == "csv":
        output = StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Data prevista", "Data recebimento", "Nome", "Categoria", "Status", "Recorrencia", "Valor", "Tipo", "Observacao"])
        for item in revenues:
            writer.writerow([item["expected_date"], item["received_date"] or "", item["name"], item["category"], item["status"], item["recurrence"], item["expected_amount"], item["type"], item["notes"] or ""])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=receitas.csv"})

    return render_template(
        "receitas.html",
        revenues=revenues,
        summary=summarize_revenues(revenues, month=period["month"], year=period["year"]),
        categories=list_revenue_category_names(),
        statuses=REVENUE_STATUS,
        recurrences=REVENUE_RECURRENCES,
        types=REVENUE_TYPES,
        today=date.today().isoformat(),
        goals=list_goals(current_user_id(), month=period["month"], year=period["year"]),
    )


@web_bp.route("/api/revenues")
@login_required
def api_revenues():
    period = selected_period()
    filters = revenue_filters_from_request()
    revenues = list_revenues(current_user_id(), **filters)
    create_log("info", "dashboard", "revenues_filtered", "Filtro de receitas aplicado", user_id=current_user_id(), details=filters)
    return jsonify({"revenues": [revenue_payload(item) for item in revenues], "summary": summarize_revenues(revenues, month=period["month"], year=period["year"])})


@web_bp.route("/api/revenues/<int:revenue_id>")
@login_required
def api_revenue_detail(revenue_id):
    revenue = get_revenue(revenue_id, current_user_id())
    if not revenue:
        return jsonify({"error": "Receita nao encontrada"}), 404
    return jsonify(revenue_payload(revenue))


@web_bp.route("/api/revenues", methods=["POST"])
@login_required
def api_revenue_create():
    period = selected_period()
    try:
        revenue_id = create_revenue(request.get_json(silent=True) or request.form, current_user_id(), month=period["month"], year=period["year"])
        attach_uploaded_file(current_user_id(), "revenue", revenue_id)
        payload = request.get_json(silent=True) or request.form
        if payload.get("goal_id") and payload.get("goal_amount"):
            add_goal_contribution(payload.get("goal_id"), current_user_id(), payload.get("goal_amount"), payload.get("received_date") or payload.get("expected_date"), "receita", revenue_id, "Parte da receita direcionada para meta")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    revenue = get_revenue(revenue_id, current_user_id())
    create_log("info", "database", "revenue_created", "Receita criada", user_id=current_user_id(), details={"id": revenue_id})
    return jsonify(revenue_payload(revenue)), 201


@web_bp.route("/api/revenues/<int:revenue_id>", methods=["PUT"])
@login_required
def api_revenue_update(revenue_id):
    if not get_revenue(revenue_id, current_user_id()):
        return jsonify({"error": "Receita nao encontrada"}), 404
    try:
        update_revenue(revenue_id, request.get_json(silent=True) or request.form, current_user_id())
        attach_uploaded_file(current_user_id(), "revenue", revenue_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    revenue = get_revenue(revenue_id, current_user_id())
    create_log("info", "database", "revenue_updated", "Receita atualizada", user_id=current_user_id(), details={"id": revenue_id})
    return jsonify(revenue_payload(revenue))


@web_bp.route("/api/revenues/<int:revenue_id>", methods=["DELETE"])
@login_required
def api_revenue_delete(revenue_id):
    if not get_revenue(revenue_id, current_user_id()):
        return jsonify({"error": "Receita nao encontrada"}), 404
    delete_revenue(revenue_id, current_user_id())
    create_log("info", "database", "revenue_deleted", "Receita excluida", user_id=current_user_id(), details={"id": revenue_id})
    return jsonify({"ok": True})


@web_bp.route("/api/revenues/<int:revenue_id>/status", methods=["PATCH", "POST"])
@login_required
def api_revenue_status(revenue_id):
    if not get_revenue(revenue_id, current_user_id()):
        return jsonify({"error": "Receita nao encontrada"}), 404
    status = (request.get_json(silent=True) or request.form).get("status")
    if status not in REVENUE_STATUS:
        return jsonify({"error": "Status invalido"}), 400
    revenue = update_revenue_status(revenue_id, status, current_user_id())
    create_log("info", "database", "revenue_status_updated", "Status da receita alterado", user_id=current_user_id(), details={"id": revenue_id, "status": status})
    return jsonify(revenue_payload(revenue))


@web_bp.route("/api/revenues/<int:revenue_id>/duplicate", methods=["POST"])
@login_required
def api_revenue_duplicate(revenue_id):
    period = selected_period()
    revenue = get_revenue(revenue_id, current_user_id())
    if not revenue:
        return jsonify({"error": "Receita nao encontrada"}), 404
    payload = dict(revenue)
    payload["name"] = f"{payload['name']} (copia)"
    payload["status"] = "prevista"
    payload["received_date"] = None
    new_id = create_revenue(payload, current_user_id(), month=period["month"], year=period["year"])
    return jsonify(revenue_payload(get_revenue(new_id, current_user_id()))), 201


@web_bp.route("/api/transactions")
@login_required
def api_transactions():
    period = selected_period()
    filters = transaction_filters_from_request()
    per_page = request.args.get("per_page", 10, type=int)
    page = request.args.get("page", 1, type=int)
    per_page = per_page if per_page in [10, 25, 50] else 10
    transactions = list_transactions(current_user_id(), **filters)
    total_records = len(transactions)
    total_pages = max((total_records + per_page - 1) // per_page, 1)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    paginated = transactions[start : start + per_page]
    create_log("info", "dashboard", "transactions_filtered", "Filtro de lancamentos aplicado", user_id=current_user_id(), details=filters)
    return jsonify(
        {
            "transactions": [transaction_payload(item) for item in paginated],
            "summary": summarize_transactions(transactions),
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "total_records": total_records,
                "start_record": start + 1 if total_records else 0,
                "end_record": min(start + per_page, total_records),
            },
        }
    )


@web_bp.route("/api/transactions/<int:transaction_id>")
@login_required
def api_transaction_detail(transaction_id):
    item = get_transaction(transaction_id, current_user_id())
    if not item:
        return jsonify({"error": "Lancamento nao encontrado"}), 404
    return jsonify(transaction_payload(item))


@web_bp.route("/api/transactions", methods=["POST"])
@login_required
def api_transaction_create():
    period = selected_period()
    payload = dict(request.get_json(silent=True) or request.form)
    try:
        transaction_id = create_transaction(payload, current_user_id(), month=period["month"], year=period["year"])
        attachment_id = attach_uploaded_file(current_user_id(), "transaction", transaction_id)
        if attachment_id:
            attachments = list_financial_attachments(current_user_id(), "transaction", transaction_id)
            if attachments:
                set_transaction_receipt_path(transaction_id, current_user_id(), attachments[0]["file_path"])
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    item = get_transaction(transaction_id, current_user_id())
    create_log("info", "database", "transaction_created_web", "Lancamento criado pela tela web", user_id=current_user_id(), details={"id": transaction_id})
    return jsonify(transaction_payload(item)), 201


@web_bp.route("/api/transactions/<int:transaction_id>", methods=["PUT"])
@login_required
def api_transaction_update(transaction_id):
    existing = get_transaction(transaction_id, current_user_id())
    if not existing:
        return jsonify({"error": "Lancamento nao encontrado"}), 404
    payload = dict(request.get_json(silent=True) or request.form)
    if "fixed_bill_id" not in payload:
        payload["fixed_bill_id"] = existing["fixed_bill_id"]
    if "revenue_id" not in payload:
        payload["revenue_id"] = existing["revenue_id"]
    try:
        update_transaction(transaction_id, payload, current_user_id())
        attachment_id = attach_uploaded_file(current_user_id(), "transaction", transaction_id)
        if attachment_id:
            attachments = list_financial_attachments(current_user_id(), "transaction", transaction_id)
            if attachments:
                set_transaction_receipt_path(transaction_id, current_user_id(), attachments[0]["file_path"])
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    item = get_transaction(transaction_id, current_user_id())
    create_log("info", "database", "transaction_updated", "Lancamento atualizado", user_id=current_user_id(), details={"id": transaction_id})
    return jsonify(transaction_payload(item))


@web_bp.route("/api/transactions/<int:transaction_id>", methods=["DELETE"])
@login_required
def api_transaction_delete(transaction_id):
    if not get_transaction(transaction_id, current_user_id()):
        return jsonify({"error": "Lancamento nao encontrado"}), 404
    delete_transaction(transaction_id, current_user_id())
    create_log("info", "database", "transaction_deleted", "Lancamento excluido", user_id=current_user_id(), details={"id": transaction_id})
    return jsonify({"ok": True})


@web_bp.route("/api/transactions/<int:transaction_id>/duplicate", methods=["POST"])
@login_required
def api_transaction_duplicate(transaction_id):
    period = selected_period()
    new_id = duplicate_transaction(transaction_id, current_user_id(), month=period["month"], year=period["year"])
    if not new_id:
        return jsonify({"error": "Lancamento nao encontrado"}), 404
    item = get_transaction(new_id, current_user_id())
    create_log("info", "database", "transaction_duplicated", "Lancamento duplicado", user_id=current_user_id(), details={"id": transaction_id, "new_id": new_id})
    return jsonify(transaction_payload(item)), 201


@web_bp.route("/contas-fixas", methods=["GET", "POST"])
@login_required
def contas_fixas():
    period = selected_period()
    if request.method == "POST":
        create_fixed_bill(request.form, current_user_id(), month=period["month"], year=period["year"])
        return redirect(url_for("web.contas_fixas"))

    bills = list_fixed_bills(current_user_id(), month=period["month"], year=period["year"])
    return render_template(
        "contas_fixas.html",
        bills=bills,
        summary=summarize_fixed_bills(bills),
        categories=list_categories("conta_fixa", include_general=True),
        statuses=TRANSACTION_STATUS,
        bill_base_statuses=["ativa", "inativa", "cancelada"],
        payment_methods=PAYMENT_METHODS,
        today=date.today().isoformat(),
        recurrences=sorted({bill["recurrence"] for bill in bills if bill["recurrence"]} | {"mensal", "quinzenal", "semanal", "anual"}),
    )


@web_bp.route("/contas-fixas/<int:bill_id>/<status>", methods=["POST"])
@login_required
def alterar_status_conta(bill_id, status):
    period = selected_period()
    update_bill_status(
        bill_id,
        status,
        current_user_id(),
        month=period["month"],
        year=period["year"],
    )
    return redirect(url_for("web.contas_fixas", month=period["month"], year=period["year"]))


@web_bp.route("/api/fixed-bills")
@login_required
def api_fixed_bills():
    period = selected_period()
    filters = bill_filters_from_request()
    bills = list_fixed_bills(current_user_id(), month=period["month"], year=period["year"], **filters)
    create_log("info", "dashboard", "fixed_bills_filtered", "Filtro de contas fixas aplicado", user_id=current_user_id(), details=filters)
    return jsonify({"bills": [fixed_bill_payload(bill) for bill in bills], "summary": summarize_fixed_bills(bills)})


@web_bp.route("/api/fixed-bills/occurrences")
@login_required
def api_fixed_bill_occurrences():
    return api_fixed_bills()


@web_bp.route("/api/fixed-bills/<int:bill_id>")
@login_required
def api_fixed_bill_detail(bill_id):
    period = selected_period()
    bill = get_fixed_bill(bill_id, current_user_id(), month=period["month"], year=period["year"])
    if not bill:
        return jsonify({"error": "Conta fixa nao encontrada"}), 404
    return jsonify(fixed_bill_payload(bill))


@web_bp.route("/api/fixed-bills", methods=["POST"])
@login_required
def api_fixed_bill_create():
    period = selected_period()
    try:
        bill_id = create_fixed_bill(request.get_json(silent=True) or request.form, current_user_id(), month=period["month"], year=period["year"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    bill = get_fixed_bill(bill_id, current_user_id(), month=period["month"], year=period["year"])
    if bill and bill.get("occurrence_id"):
        try:
            attach_uploaded_file(current_user_id(), "fixed_bill_occurrence", bill["occurrence_id"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    create_log("info", "database", "fixed_bill_created", "Conta fixa criada", user_id=current_user_id(), details={"id": bill_id})
    return jsonify(fixed_bill_payload(bill)), 201


@web_bp.route("/api/fixed-bills/<int:bill_id>", methods=["PUT"])
@login_required
def api_fixed_bill_update(bill_id):
    period = selected_period()
    if not get_fixed_bill(bill_id, current_user_id(), month=period["month"], year=period["year"]):
        return jsonify({"error": "Conta fixa nao encontrada"}), 404
    try:
        update_fixed_bill(bill_id, request.get_json(silent=True) or request.form, current_user_id(), month=period["month"], year=period["year"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    bill = get_fixed_bill(bill_id, current_user_id(), month=period["month"], year=period["year"])
    if bill and bill.get("occurrence_id"):
        try:
            attach_uploaded_file(current_user_id(), "fixed_bill_occurrence", bill["occurrence_id"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    create_log("info", "database", "fixed_bill_updated", "Conta fixa atualizada", user_id=current_user_id(), details={"id": bill_id})
    return jsonify(fixed_bill_payload(bill))


@web_bp.route("/api/fixed-bills/<int:bill_id>", methods=["DELETE"])
@login_required
def api_fixed_bill_delete(bill_id):
    if not get_fixed_bill(bill_id, current_user_id()):
        return jsonify({"error": "Conta fixa nao encontrada"}), 404
    delete_fixed_bill(bill_id, current_user_id())
    create_log("info", "database", "fixed_bill_deleted", "Conta fixa excluida", user_id=current_user_id(), details={"id": bill_id})
    return jsonify({"ok": True})


@web_bp.route("/api/fixed-bills/<int:bill_id>/status", methods=["PATCH", "POST"])
@login_required
def api_fixed_bill_status(bill_id):
    period = selected_period()
    if not get_fixed_bill(bill_id, current_user_id(), month=period["month"], year=period["year"]):
        return jsonify({"error": "Conta fixa nao encontrada"}), 404
    data = request.get_json(silent=True) or request.form
    status = data.get("status")
    if status not in TRANSACTION_STATUS:
        return jsonify({"error": "Status invalido"}), 400
    update_bill_status(bill_id, status, current_user_id(), month=period["month"], year=period["year"])
    bill = get_fixed_bill(bill_id, current_user_id(), month=period["month"], year=period["year"])
    create_log("info", "database", "fixed_bill_status_updated", "Status da conta fixa alterado", user_id=current_user_id(), details={"id": bill_id, "status": status})
    return jsonify(fixed_bill_payload(bill))


@web_bp.route("/comprovantes")
@login_required
def comprovantes():
    period = selected_period()
    create_log(
        "info",
        "dashboard",
        "receipts_module_redirected",
        "Comprovantes agora ficam vinculados aos lancamentos, receitas e contas fixas.",
        user_id=current_user_id(),
    )
    return redirect(url_for("web.lancamentos", month=period["month"], year=period["year"]))


@web_bp.route("/api/receipts")
@login_required
def api_receipts():
    period = selected_period()
    return jsonify(
        {
            "message": "Comprovantes agora ficam vinculados aos lancamentos, receitas e contas fixas.",
            "attachments": [dict(item) for item in list_financial_attachments(current_user_id())],
            "month": period["month"],
            "year": period["year"],
        }
    )


@web_bp.route("/api/attachments")
@login_required
def api_attachments():
    period = selected_period()
    linked_type = request.args.get("linked_type") or None
    linked_id = request.args.get("linked_id", type=int)
    return jsonify(
        {
            "attachments": [dict(item) for item in list_financial_attachments(current_user_id(), linked_type, linked_id)],
            "month": period["month"],
            "year": period["year"],
        }
    )


@web_bp.route("/api/alerts")
@login_required
def api_alerts():
    period = selected_period()
    alerts = [dict(item) for item in list_alerts(current_user_id(), month=period["month"], year=period["year"])]
    return jsonify({"alerts": alerts, "month": period["month"], "year": period["year"]})


@web_bp.route("/api/reports")
@login_required
def api_reports():
    period = selected_period()
    data = get_monthly_report_data(
        current_user_id(),
        month=period["month"],
        year=period["year"],
        evolution_filter=request.args.get("range", "12"),
    )
    return jsonify(data)


@web_bp.route("/api/goals")
@login_required
def api_goals():
    period = selected_period()
    return jsonify({"month": period["month"], "year": period["year"], **goals_page_data(current_user_id(), month=period["month"], year=period["year"])})


@web_bp.route("/relatorios")
@login_required
def relatorios():
    period = selected_period()
    data = get_monthly_report_data(current_user_id(), month=period["month"], year=period["year"])
    return render_template("relatorios.html", data=data)


@web_bp.route("/relatorios/export/pdf")
@login_required
def relatorios_export_pdf():
    period = selected_period()
    pdf = generate_monthly_report_pdf(current_user_id(), month=period["month"], year=period["year"])
    filename = f"relatorio_financeiro_{period['month']:02d}_{period['year']}.pdf"
    return send_file(pdf, mimetype="application/pdf", as_attachment=True, download_name=filename)


@web_bp.route("/relatorios/export/csv")
@login_required
def relatorios_export_csv():
    period = selected_period()
    csv_data = generate_report_csv(current_user_id(), month=period["month"], year=period["year"])
    filename = f"relatorio_financeiro_{period['month']:02d}_{period['year']}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@web_bp.route("/relatorios/export/xlsx")
@login_required
def relatorios_export_xlsx():
    period = selected_period()
    workbook = generate_report_xlsx(current_user_id(), month=period["month"], year=period["year"])
    filename = f"relatorio_financeiro_{period['month']:02d}_{period['year']}.xlsx"
    return send_file(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@web_bp.route("/assistente")
@login_required
def assistente():
    period = selected_period()
    return render_template("assistente.html", data=get_dashboard_data(current_user_id(), month=period["month"], year=period["year"]))


@web_bp.route("/admin/usuarios")
@admin_required
def admin_users():
    return render_template("admin_users.html", users=list_users(request.args), filters=request.args, kpis=admin_kpis())


@web_bp.route("/admin/usuarios/novo", methods=["GET", "POST"])
@admin_required
def admin_user_create():
    error = None
    if request.method == "POST":
        try:
            user_id = admin_create_user(request.form)
            create_log("info", "admin", "user_created", "Usuario criado pelo admin", user_id=current_user_id(), details={"created_user_id": user_id})
            return redirect(url_for("web.admin_user_detail", user_id=user_id))
        except ValueError as exc:
            error = str(exc)
    return render_template("admin_user_form.html", user=None, error=error, mode="create")


@web_bp.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_user_create():
    try:
        user_id = admin_create_user(request.get_json(silent=True) or request.form)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    user = get_user(user_id)
    create_log("info", "admin", "user_created", "Usuario criado pelo admin", user_id=current_user_id(), details={"created_user_id": user_id})
    payload = dict(user)
    payload["telegram_badge"] = telegram_badge(payload.get("telegram_status"))
    payload["total_transactions"] = 0
    return jsonify({"user": payload}), 201


@web_bp.route("/admin/usuarios/<int:user_id>")
@admin_required
def admin_user_detail(user_id):
    return render_template("admin_user_detail.html", details=user_details(user_id))


@web_bp.route("/admin/usuarios/<int:user_id>/telegram/gerar-codigo", methods=["POST"])
@admin_required
def admin_user_telegram_generate(user_id):
    if not get_user(user_id):
        return redirect(url_for("web.admin_users"))
    code = generate_link_code(user_id)
    create_log("info", "admin", "telegram_link_code_generated", "Codigo Telegram gerado pelo admin", user_id=current_user_id(), details={"target_user_id": user_id, "expires_at": code["expires_at"]})
    return redirect(url_for("web.admin_user_detail", user_id=user_id))


@web_bp.route("/admin/usuarios/<int:user_id>/telegram/desvincular", methods=["POST"])
@admin_required
def admin_user_telegram_unlink(user_id):
    if not get_user(user_id):
        return redirect(url_for("web.admin_users"))
    unlink_telegram_account(user_id)
    create_log("info", "admin", "telegram_unlinked", "Telegram desvinculado pelo admin", user_id=current_user_id(), details={"target_user_id": user_id})
    return redirect(url_for("web.admin_user_detail", user_id=user_id))


@web_bp.route("/admin/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@admin_required
def admin_user_edit(user_id):
    user = get_user(user_id)
    if not user:
        return redirect(url_for("web.admin_users"))
    error = None
    if request.method == "POST":
        try:
            update_user(user_id, request.form)
            create_log("info", "admin", "user_updated", "Usuario atualizado pelo admin", user_id=current_user_id(), details={"updated_user_id": user_id})
            return redirect(url_for("web.admin_user_detail", user_id=user_id))
        except ValueError as exc:
            error = str(exc)
    return render_template("admin_user_form.html", user=user, error=error, mode="edit")


@web_bp.route("/admin/usuarios/<int:user_id>/toggle", methods=["POST"])
@admin_required
def admin_user_toggle(user_id):
    toggle_user_status(user_id)
    return redirect(url_for("web.admin_users"))


@web_bp.route("/admin/logs")
@admin_required
def admin_logs():
    return render_template("admin_logs.html", logs=list_logs())


@web_bp.route("/categorias")
@login_required
def categorias_redirect():
    period = selected_period()
    return redirect(url_for("web.configuracoes_categorias", month=period["month"], year=period["year"]))


@web_bp.route("/configuracoes")
@login_required
def configuracoes():
    return render_template("configuracoes.html")


@web_bp.route("/configuracoes/telegram", methods=["GET", "POST"])
@login_required
def configuracoes_telegram():
    message = None
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "generate":
                code = generate_link_code(current_user_id())
                message = f"Codigo gerado: {code['code']}"
                create_log("info", "telegram", "telegram_link_code_created", "Codigo de vinculacao gerado", user_id=current_user_id())
            elif action == "unlink":
                unlink_telegram_account(current_user_id())
                message = "Telegram desvinculado com sucesso."
                create_log("info", "telegram", "telegram_unlinked", "Telegram desvinculado pelo usuario", user_id=current_user_id())
        except ValueError as exc:
            error = str(exc)
    return render_template("configuracoes_telegram.html", telegram_status=get_user_telegram_status(current_user_id()), message=message, error=error)


@web_bp.route("/configuracoes/categorias")
@login_required
def configuracoes_categorias():
    return render_template(
        "configuracoes_categorias.html",
        categories=[dict(item) for item in list_categories(include_inactive=True)],
        category_types=CATEGORY_TYPES,
    )


@web_bp.route("/api/categories")
@login_required
def api_categories():
    category_type = request.args.get("type") or None
    include_inactive = request.args.get("include_inactive") == "1"
    include_general = request.args.get("include_general", "1") != "0"
    return jsonify(
        {
            "categories": [dict(item) for item in list_categories(category_type, include_inactive=include_inactive, include_general=include_general)],
            "types": CATEGORY_TYPES,
        }
    )


@web_bp.route("/api/categories", methods=["POST"])
@login_required
def api_category_create():
    try:
        category = create_category(request.get_json(silent=True) or request.form)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    create_log("info", "database", "category_created", "Categoria criada", user_id=current_user_id(), details=dict(category))
    return jsonify(dict(category)), 201


@web_bp.route("/api/categories/<int:category_id>", methods=["PUT"])
@login_required
def api_category_update(category_id):
    if not get_category(category_id):
        return jsonify({"error": "Categoria nao encontrada"}), 404
    try:
        category = update_category(category_id, request.get_json(silent=True) or request.form)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    create_log("info", "database", "category_updated", "Categoria atualizada", user_id=current_user_id(), details=dict(category))
    return jsonify(dict(category))


@web_bp.route("/api/categories/<int:category_id>/deactivate", methods=["PATCH", "POST"])
@login_required
def api_category_deactivate(category_id):
    category = deactivate_category(category_id)
    if not category:
        return jsonify({"error": "Categoria nao encontrada"}), 404
    create_log("info", "database", "category_deactivated", "Categoria desativada", user_id=current_user_id(), details={"id": category_id})
    return jsonify(dict(category))


@web_bp.route("/api/categories/<int:category_id>", methods=["DELETE"])
@login_required
def api_category_delete(category_id):
    if not get_category(category_id):
        return jsonify({"error": "Categoria nao encontrada"}), 404
    try:
        delete_category(category_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 409
    create_log("info", "database", "category_deleted", "Categoria excluida", user_id=current_user_id(), details={"id": category_id})
    return jsonify({"ok": True})


@web_bp.route("/metas")
@login_required
def metas():
    period = selected_period()
    return render_template("metas.html", data=goals_page_data(current_user_id(), month=period["month"], year=period["year"]), today=date.today().isoformat())


@web_bp.route("/api/goals", methods=["POST"])
@login_required
def api_goal_create():
    try:
        goal_id = create_goal(request.get_json(silent=True) or request.form, current_user_id())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    period = selected_period()
    goal = get_goal(goal_id, current_user_id(), month=period["month"], year=period["year"])
    create_log("info", "database", "goal_created", "Meta criada", user_id=current_user_id(), details={"id": goal_id})
    return jsonify(goal), 201


@web_bp.route("/api/goals/<int:goal_id>")
@login_required
def api_goal_detail(goal_id):
    period = selected_period()
    goal = get_goal(goal_id, current_user_id(), month=period["month"], year=period["year"])
    if not goal:
        return jsonify({"error": "Meta nao encontrada"}), 404
    return jsonify({"goal": goal, "contributions": [dict(item) for item in list_goal_contributions(current_user_id(), goal_id)]})


@web_bp.route("/api/goals/<int:goal_id>", methods=["PUT"])
@login_required
def api_goal_update(goal_id):
    if not get_goal(goal_id, current_user_id()):
        return jsonify({"error": "Meta nao encontrada"}), 404
    try:
        goal = update_goal(goal_id, request.get_json(silent=True) or request.form, current_user_id())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    create_log("info", "database", "goal_updated", "Meta atualizada", user_id=current_user_id(), details={"id": goal_id})
    return jsonify(goal)


@web_bp.route("/api/goals/<int:goal_id>/contributions", methods=["POST"])
@login_required
def api_goal_contribution(goal_id):
    payload = request.get_json(silent=True) or request.form
    try:
        contribution_id = add_goal_contribution(
            goal_id,
            current_user_id(),
            payload.get("amount"),
            payload.get("contribution_date") or date.today().isoformat(),
            payload.get("source") or "manual",
            payload.get("source_id"),
            payload.get("notes"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    create_log("info", "database", "goal_contribution_created", "Contribuicao em meta criada", user_id=current_user_id(), details={"id": contribution_id, "goal_id": goal_id})
    period = selected_period()
    return jsonify({"goal": get_goal(goal_id, current_user_id(), month=period["month"], year=period["year"]), "contribution_id": contribution_id}), 201


@web_bp.route("/api/goals/<int:goal_id>/status", methods=["PATCH", "POST"])
@login_required
def api_goal_status(goal_id):
    payload = request.get_json(silent=True) or request.form
    goal = update_goal_status(goal_id, current_user_id(), payload.get("status"))
    if not goal:
        return jsonify({"error": "Meta nao encontrada"}), 404
    return jsonify(goal)


@web_bp.route("/api/goals/<int:goal_id>", methods=["DELETE"])
@login_required
def api_goal_delete(goal_id):
    if not get_goal(goal_id, current_user_id()):
        return jsonify({"error": "Meta nao encontrada"}), 404
    delete_goal(goal_id, current_user_id())
    create_log("info", "database", "goal_deleted", "Meta excluida", user_id=current_user_id(), details={"id": goal_id})
    return jsonify({"ok": True})


@web_bp.route("/alertas")
@login_required
def placeholder():
    return render_template("placeholder.html", title=request.path.strip("/").replace("-", " ").title())
