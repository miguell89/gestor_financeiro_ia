import re
import unicodedata
from datetime import date

from ai.gemini_client import GeminiClient


def parse_money(text):
    match = re.search(r"(\d+[,.]?\d*)", text)
    if not match:
        return 0
    return float(match.group(1).replace(",", "."))


def simulated_intent(text):
    lower = text.lower()
    normalized = unicodedata.normalize("NFKD", lower).encode("ascii", "ignore").decode("ascii")
    amount = parse_money(lower)

    if "recebi" in normalized or "salario" in normalized:
        return {
            "intent": "create_transaction",
            "type": "receita",
            "amount": amount,
            "category": "Salario",
            "description": text,
            "date": date.today().isoformat(),
        }

    if "paguei" in normalized and ("internet" in normalized or "celular" in normalized):
        return {"intent": "mark_bill_paid", "bill_name": "Internet" if "internet" in normalized else "Celular"}

    if "proximo mes" in normalized or "adiar" in normalized:
        bill_name = "Celular" if "celular" in normalized else "Internet" if "internet" in normalized else ""
        return {"intent": "postpone_bill", "bill_name": bill_name}

    if "semana" in normalized or "vencem" in normalized or "vence" in normalized:
        return {"intent": "list_due_bills"}

    if "quanto" in normalized or "resumo" in normalized:
        return {"intent": "monthly_summary"}

    return {
        "intent": "create_transaction",
        "type": "despesa",
        "amount": amount,
        "category": "Alimentacao" if "mercado" in normalized else "Lazer",
        "description": text,
        "date": date.today().isoformat(),
    }


def interpretar_mensagem(text):
    fallback = simulated_intent(text)
    normalized = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    local_patterns = [
        "gastei",
        "paguei",
        "recebi",
        "salario",
        "resumo",
        "quanto",
        "vencem",
        "vence",
        "adiar",
        "proximo mes",
    ]
    if any(pattern in normalized for pattern in local_patterns):
        return fallback

    today = date.today().isoformat()
    prompt = f"""
    Voce e um assistente financeiro brasileiro.
    Interprete a mensagem abaixo e responda apenas JSON valido, sem markdown.
    Data de hoje: {today}.

    Intencoes possiveis:
    - create_transaction
    - mark_bill_paid
    - postpone_bill
    - list_due_bills
    - monthly_summary

    Campos:
    intent: string
    type: "receita" ou "despesa"
    amount: numero
    category: uma destas categorias se fizer sentido: Salario, Alimentacao, Moradia, Transporte, Celular, Lazer
    description: resumo curto
    date: data ISO yyyy-mm-dd quando houver, senao {today}
    bill_name: nome da conta quando houver

    Mensagem: {text}
    """
    return GeminiClient().generate_json(prompt, fallback)
