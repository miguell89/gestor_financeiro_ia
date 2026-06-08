from __future__ import annotations

import csv
import math
import tempfile
import zipfile
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from app.database import db
from app.services.finance_service import (
    generate_monthly_fixed_bill_occurrences,
    get_dashboard_data,
    list_alerts,
    list_fixed_bills,
    list_revenues,
    list_transactions,
    money,
    month_prefix,
    percent_change,
    selected_month_year,
)
from app.services.goal_service import list_goals, summarize_goals

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


def brl(value):
    formatted = f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def previous_period(month, year):
    month, year = selected_month_year(month, year)
    return (12, year - 1) if month == 1 else (month - 1, year)


def shift_month(month, year, delta):
    month, year = selected_month_year(month, year)
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return month, year


def period_label(month, year):
    month, year = selected_month_year(month, year)
    return f"{MONTH_NAMES[month]}/{year}"


def _rowdicts(rows):
    return [dict(row) for row in rows]


def _monthly_totals(user_id, month, year):
    prefix = month_prefix(month, year)
    with db() as conn:
        transactions = conn.execute(
            """
            select t.*, c.name as category_name, c.color as category_color
            from transactions t
            left join categories c on c.id = t.category_id
            where t.user_id = ? and t.date like ?
            order by t.date desc, t.id desc
            """,
            (user_id, f"{prefix}%"),
        ).fetchall()
        revenues = conn.execute(
            """
            select *
            from revenues
            where user_id = ? and (expected_date like ? or received_date like ?)
            order by expected_date desc, id desc
            """,
            (user_id, f"{prefix}%", f"{prefix}%"),
        ).fetchall()
    receitas = sum(money(t["amount"]) for t in transactions if t["type"] == "receita" and t["status"] == "pago")
    despesas = sum(money(t["amount"]) for t in transactions if t["type"] == "despesa" and t["status"] == "pago")
    receitas_previstas = sum(money(r["expected_amount"]) for r in revenues if r["status"] in ("prevista", "atrasada"))
    return {
        "transactions": transactions,
        "revenues": revenues,
        "receitas": receitas,
        "despesas": despesas,
        "saldo": receitas - despesas,
        "receitas_previstas": receitas_previstas,
    }


def _category_breakdown(transactions, despesas):
    totals = {}
    colors = {}
    for item in transactions:
        if item["type"] != "despesa" or item["status"] != "pago":
            continue
        name = item["category_name"] or "Sem categoria"
        totals[name] = totals.get(name, 0) + money(item["amount"])
        colors[name] = item["category_color"] or "#38bdf8"
    return [
        {
            "name": name,
            "total": total,
            "percent": round((total / despesas) * 100, 1) if despesas else 0,
            "color": colors.get(name, "#38bdf8"),
        }
        for name, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def _evolution(user_id, month, year, months=12, current_year=False):
    points = []
    if current_year:
        start = 1
        values = [(m, year) for m in range(start, month + 1)]
    else:
        values = [shift_month(month, year, offset) for offset in range(-(months - 1), 1)]
    for item_month, item_year in values:
        totals = _monthly_totals(user_id, item_month, item_year)
        points.append(
            {
                "month": item_month,
                "year": item_year,
                "label": f"{MONTH_NAMES[item_month][:3]}/{str(item_year)[2:]}",
                "receitas": totals["receitas"],
                "despesas": totals["despesas"],
                "saldo": totals["saldo"],
            }
        )
    return points


def _goals_from_data(user_id, month, year, data, dashboard):
    real_goals = list_goals(user_id, month, year)
    if real_goals:
        return [
            {
                "name": goal["name"],
                "current": goal["current_calculated"],
                "target": goal["target_amount"],
                "percent": goal["percent"],
                "status": goal["status"],
                "missing": goal["missing_amount"],
            }
            for goal in real_goals[:3]
        ]
    return [
        {
            "name": "Economia do mes",
            "current": min(data["summary"]["saldo_final"], dashboard["goal_target"]),
            "target": dashboard["goal_target"],
            "percent": dashboard["goal_percent"],
        }
    ]


def generate_ai_report_summary(report_data):
    summary = report_data["summary"]
    previous = report_data["previous_summary"]
    categories = report_data["categories"]
    lines = []
    if previous["despesas"]:
        delta = percent_change(summary["despesas"], previous["despesas"])
        direction = "mais" if delta > 0 else "menos"
        lines.append(f"Voce gastou {abs(delta)}% {direction} em comparacao ao mes anterior.")
    if categories:
        top = categories[0]
        lines.append(f"{top['name']} foi sua maior categoria, com {brl(top['total'])}.")
    revenue_delta = percent_change(summary["receitas"], previous["receitas"])
    if revenue_delta:
        direction = "cresceram" if revenue_delta > 0 else "reduziram"
        lines.append(f"Receitas {direction} {abs(revenue_delta)}% no periodo.")
    lines.append("Seu saldo final foi positivo." if summary["saldo_final"] >= 0 else "Seu saldo final ficou negativo e pede atencao.")
    if report_data["goals"]:
        goal = report_data["goals"][0]
        lines.append(f"Mantendo esse ritmo, a meta {goal['name']} esta em {goal['percent']}%.")
    return lines


def _alert_opportunities(data, previous_data, fixed_bills):
    alerts = []
    current_by_name = {bill["name"]: money(bill["amount"]) for bill in fixed_bills}
    previous_bills = list_fixed_bills(data["user_id"], month=previous_data["month"], year=previous_data["year"])
    previous_by_name = {bill["name"]: money(bill["amount"]) for bill in previous_bills}
    for name, total in current_by_name.items():
        old = previous_by_name.get(name, 0)
        if old and total > old * 1.2:
            alerts.append({"type": "warning", "message": f"{name} aumentou {percent_change(total, old)}% em relacao ao mes anterior."})
    postponed = [bill for bill in fixed_bills if bill["occurrence_status"] == "postponed"]
    if postponed:
        alerts.append({"type": "danger", "message": f"Voce possui {len(postponed)} conta(s) adiadas para o proximo mes."})
    if data["summary"]["economia_mes"] > 0:
        alerts.append({"type": "success", "message": f"Voce economizou {brl(data['summary']['economia_mes'])} este mes."})
    persisted = [dict(item) for item in list_alerts(data["user_id"], month=data["month"], year=data["year"])]
    alerts.extend({"type": item.get("type", "info"), "message": item["message"]} for item in persisted[:3])
    if not alerts:
        alerts.append({"type": "info", "message": "Nao ha alertas criticos para esta competencia."})
    return alerts[:5]


def get_monthly_report_data(user_id, month=None, year=None, evolution_filter="12"):
    month, year = selected_month_year(month, year)
    generate_monthly_fixed_bill_occurrences(user_id, month, year)
    dashboard = get_dashboard_data(user_id, month=month, year=year)
    totals = _monthly_totals(user_id, month, year)
    previous_month, previous_year = previous_period(month, year)
    previous = _monthly_totals(user_id, previous_month, previous_year)
    current_goals_summary = summarize_goals(user_id, month, year)
    previous_goals_summary = summarize_goals(user_id, previous_month, previous_year)
    fixed_bills = list_fixed_bills(user_id, month=month, year=year)
    categories = _category_breakdown(totals["transactions"], totals["despesas"])
    filters = {"3": 3, "6": 6, "12": 12}
    evolution = _evolution(user_id, month, year, months=filters.get(str(evolution_filter), 12), current_year=str(evolution_filter) == "year")
    summary = {
        "receitas": totals["receitas"],
        "despesas": totals["despesas"],
        "saldo_final": totals["saldo"],
        "saldo_previsto": dashboard["saldo_previsto"],
        "economia_mes": max(totals["saldo"], 0),
        "meta_atingida": dashboard["goal_percent"],
        "total_movements": len(totals["transactions"]) + len(totals["revenues"]) + len(fixed_bills),
    }
    data = {
        "user_id": user_id,
        "month": month,
        "year": year,
        "label": period_label(month, year),
        "summary": summary,
        "previous_summary": {
            "receitas": previous["receitas"],
            "despesas": previous["despesas"],
            "saldo_final": previous["saldo"],
            "saldo_previsto": get_dashboard_data(user_id, month=previous_month, year=previous_year)["saldo_previsto"],
            "economia_mes": max(previous["saldo"], 0),
            "meta_atingida": previous_goals_summary["average_percent"] if previous_goals_summary["total_goals"] else percent_change(max(previous["saldo"], 0), dashboard["goal_target"]),
        },
        "cards": [],
        "evolution": evolution,
        "categories": categories,
        "goals": [],
        "transactions": _rowdicts(totals["transactions"]),
        "revenues": _rowdicts(totals["revenues"]),
        "fixed_bills": [dict(item) for item in fixed_bills],
        "has_data": bool(totals["transactions"] or totals["revenues"] or fixed_bills),
    }
    data["goals"] = _goals_from_data(user_id, month, year, data, dashboard)
    if current_goals_summary["total_goals"]:
        summary["meta_atingida"] = current_goals_summary["average_percent"]
    previous_meta = data["previous_summary"]["meta_atingida"]
    card_map = [
        ("Total de receitas", "receitas", "money", "up"),
        ("Total de despesas", "despesas", "money", "down"),
        ("Saldo final", "saldo_final", "money", "wallet"),
        ("Saldo previsto", "saldo_previsto", "money", "chart"),
        ("Economia do mes", "economia_mes", "money", "save"),
        ("Meta atingida", "meta_atingida", "percent", "target"),
    ]
    for title, key, kind, icon in card_map:
        current = summary[key]
        prev = previous_meta if key == "meta_atingida" else data["previous_summary"].get(key, 0)
        data["cards"].append(
            {
                "title": title,
                "key": key,
                "icon": icon,
                "value": f"{round(current)}%" if kind == "percent" else brl(current),
                "delta": percent_change(current, prev),
                "delta_label": f"em relacao a {MONTH_NAMES[previous_month]}/{previous_year}",
            }
        )
    data["ai_summary"] = generate_ai_report_summary(data)
    data["alerts"] = _alert_opportunities(data, {"month": previous_month, "year": previous_year}, fixed_bills)
    return data


def generate_monthly_summary_text(report_data):
    if not report_data["has_data"]:
        return "Nao encontrei movimentacoes para esse mes ainda."
    summary = report_data["summary"]
    lines = [
        f"Resumo financeiro de {report_data['label']}",
        "",
        f"Receitas: {brl(summary['receitas'])}",
        f"Despesas: {brl(summary['despesas'])}",
        f"Saldo final: {brl(summary['saldo_final'])}",
        f"Saldo previsto: {brl(summary['saldo_previsto'])}",
        f"Meta atingida: {summary['meta_atingida']}%",
        "",
        "Principais gastos:",
    ]
    if report_data["categories"]:
        lines.extend([f"{index}. {item['name']}: {brl(item['total'])}" for index, item in enumerate(report_data["categories"][:3], start=1)])
    else:
        lines.append("Nenhuma despesa categorizada.")
    lines.extend(["", "Analise IA:"])
    lines.extend(report_data["ai_summary"])
    return "\n".join(lines)


def _pdf_escape(text):
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf(lines):
    content = ["BT", "/F1 12 Tf", "50 800 Td", "16 TL"]
    for line in lines:
        content.append(f"({_pdf_escape(line)}) Tj")
        content.append("T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    result = BytesIO()
    result.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(result.tell())
        result.write(f"{index} 0 obj\n".encode())
        result.write(obj)
        result.write(b"\nendobj\n")
    xref = result.tell()
    result.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.write(f"{offset:010d} 00000 n \n".encode())
    result.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    result.seek(0)
    return result


def generate_monthly_report_pdf(user_id, month=None, year=None):
    data = get_monthly_report_data(user_id, month, year)
    summary = data["summary"]
    lines = [
        f"Relatorio financeiro - {data['label']}",
        "",
        f"Receitas: {brl(summary['receitas'])}",
        f"Despesas: {brl(summary['despesas'])}",
        f"Saldo final: {brl(summary['saldo_final'])}",
        f"Saldo previsto: {brl(summary['saldo_previsto'])}",
        f"Economia do mes: {brl(summary['economia_mes'])}",
        f"Meta atingida: {summary['meta_atingida']}%",
        "",
        "Gastos por categoria:",
    ]
    lines.extend([f"- {item['name']}: {brl(item['total'])} ({item['percent']}%)" for item in data["categories"][:8]] or ["- Sem despesas categorizadas"])
    lines.extend(["", "Metas:"])
    lines.extend([f"- {item['name']}: {brl(item['current'])} / {brl(item['target'])} ({item['percent']}%)" for item in data["goals"]])
    lines.extend(["", "Alertas:"])
    lines.extend([f"- {item['message']}" for item in data["alerts"]])
    lines.extend(["", "Resumo inteligente IA:"])
    lines.extend([f"- {line}" for line in data["ai_summary"]])
    return _simple_pdf(lines)


def generate_report_csv(user_id, month=None, year=None):
    data = get_monthly_report_data(user_id, month, year)
    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Tipo", "Data", "Descricao", "Categoria", "Status", "Valor"])
    for item in data["transactions"]:
        writer.writerow(["Lancamento", item.get("date"), item.get("description"), item.get("category_name"), item.get("status"), item.get("amount")])
    for item in data["revenues"]:
        writer.writerow(["Receita", item.get("expected_date"), item.get("name"), item.get("category"), item.get("status"), item.get("expected_amount")])
    for item in data["fixed_bills"]:
        writer.writerow(["Conta fixa", item.get("due_date"), item.get("name"), item.get("category_name"), item.get("occurrence_status"), item.get("amount")])
    writer.writerow([])
    writer.writerow(["Resumo", data["label"], "Receitas", data["summary"]["receitas"]])
    writer.writerow(["Resumo", data["label"], "Despesas", data["summary"]["despesas"]])
    writer.writerow(["Resumo", data["label"], "Saldo final", data["summary"]["saldo_final"]])
    return output.getvalue()


def generate_report_xlsx(user_id, month=None, year=None):
    csv_data = generate_report_csv(user_id, month, year)
    rows = [row.split(";") for row in csv_data.splitlines()]
    shared = []
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            cell = f"{chr(64 + col_index)}{row_index}"
            shared.append(value)
            cells.append(f'<c r="{cell}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    workbook = BytesIO()
    with zipfile.ZipFile(workbook, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Relatorio" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    workbook.seek(0)
    return workbook


def generate_monthly_summary_image(user_id, month=None, year=None):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    data = get_monthly_report_data(user_id, month, year)
    image = Image.new("RGB", (900, 520), "#07101f")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default()
    draw.rectangle((0, 0, 900, 520), fill="#07101f")
    draw.text((42, 34), f"Resumo financeiro - {data['label']}", fill="#edf4ff", font=title_font)
    y = 96
    for label, value, color in [
        ("Receitas", brl(data["summary"]["receitas"]), "#38f2a8"),
        ("Despesas", brl(data["summary"]["despesas"]), "#f97388"),
        ("Saldo", brl(data["summary"]["saldo_final"]), "#38bdf8"),
        ("Meta", f"{data['summary']['meta_atingida']}%", "#8b5cf6"),
    ]:
        draw.rounded_rectangle((42, y, 410, y + 72), radius=14, outline="#243454", fill="#101d37")
        draw.text((64, y + 15), label, fill="#a9b7d3", font=title_font)
        draw.text((64, y + 40), value, fill=color, font=title_font)
        y += 90
    top = data["categories"][:4]
    y = 112
    draw.text((500, 84), "Top categorias", fill="#edf4ff", font=title_font)
    for item in top:
        width = min(320, int((item["percent"] / 100) * 320))
        draw.text((500, y), f"{item['name']} - {brl(item['total'])}", fill="#d9e5ff", font=title_font)
        draw.rounded_rectangle((500, y + 24, 820, y + 38), radius=7, fill="#1b2a45")
        draw.rounded_rectangle((500, y + 24, 500 + width, y + 38), radius=7, fill=item.get("color") or "#38bdf8")
        y += 70
    path = Path(tempfile.gettempdir()) / f"resumo_financeiro_{user_id}_{month}_{year}.png"
    image.save(path)
    return path


def send_report_to_telegram(user_id, month=None, year=None, format="text"):
    data = get_monthly_report_data(user_id, month, year)
    if format == "pdf":
        pdf = generate_monthly_report_pdf(user_id, month, year)
        path = Path(tempfile.gettempdir()) / f"relatorio_financeiro_{user_id}_{data['month']}_{data['year']}.pdf"
        path.write_bytes(pdf.getvalue())
        return {"type": "document", "path": path, "caption": f"Relatorio financeiro de {data['label']}"}
    if format == "image":
        path = generate_monthly_summary_image(user_id, month, year)
        if path:
            return {"type": "photo", "path": path, "caption": f"Resumo financeiro de {data['label']}"}
    return {"type": "text", "text": generate_monthly_summary_text(data)}
