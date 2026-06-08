import random

from ai.gemini_client import GeminiClient


def format_money(value):
    return f"{float(value or 0):.2f}"


def fallback_response(evento, dados_financeiros, tom="divertido"):
    valor = format_money(dados_financeiros.get("valor"))
    categoria = dados_financeiros.get("categoria") or "geral"
    percentual = dados_financeiros.get("percentual_orcamento") or 0
    saldo_previsto = format_money(dados_financeiros.get("saldo_previsto"))

    responses = {
        "lancamento": [
            f"Registrei R$ {valor} em {categoria}. Esse Pix passou voando, mas eu capturei ele no sistema.",
            f"Anotado: R$ {valor} em {categoria}. O caixa sentiu, mas agora esta tudo sob controle.",
            f"Lancamento salvo: R$ {valor} em {categoria}. A planilha mental pode descansar.",
        ],
        "receita": [
            f"Receita de R$ {valor} registrada. O caixa ganhou reforco.",
            f"Entrada salva: R$ {valor}. Hoje o saldo respirou melhor.",
            f"Recebi o recado: R$ {valor} entrou no radar financeiro.",
        ],
        "conta_paga": [
            "Conta paga. Um boleto a menos rondando sua paz.",
            "Pronto, conta marcada como paga. Menos uma pendencia fazendo sombra.",
            "Pagamento registrado. Esse boleto perdeu a forca.",
        ],
        "conta_adiada": [
            "Conta adiada. Ela saiu da frente por enquanto, mas eu deixei marcada para nao sumir do radar.",
            "Adiei a conta. So nao vale fingir que ela evaporou, combinado?",
            "Conta empurrada para depois e registrada no sistema.",
        ],
        "alerta": [
            f"Voce ja usou {percentual}% do orcamento de {categoria}. Vamos pisar no freio antes que o lanche vire vilao?",
            f"Alerta em {categoria}: {percentual}% do limite ja foi usado. Bora ajustar a rota.",
        ],
        "resumo_dashboard": [
            f"Seu painel esta atualizado. Saldo previsto de R$ {saldo_previsto}; o caixa esta sob vigilancia elegante.",
            f"Resumo pronto. Saldo previsto: R$ {saldo_previsto}. Seus numeros estao organizados.",
        ],
    }

    if tom == "profissional":
        return f"Registro concluido. Evento: {evento}. Valor: R$ {valor}. Categoria: {categoria}."

    if tom == "firme":
        return f"Registrado. R$ {valor} em {categoria}. Continue acompanhando o limite."

    if tom == "conselheiro":
        return f"Anotei R$ {valor} em {categoria}. Registrar agora ajuda voce a decidir melhor depois."

    return random.choice(responses.get(evento, responses["lancamento"]))


def gerar_resposta_humanizada(evento, dados_financeiros, tom="divertido"):
    fallback = fallback_response(evento, dados_financeiros, tom)

    if evento == "resumo_dashboard":
        return fallback

    prompt = f"""
    Voce e o assistente financeiro do sistema Meu Gestor Financeiro IA.
    Gere UMA resposta curta em portugues do Brasil para o usuario.

    Regras:
    - Nao repita sempre a mesma frase.
    - Maximo de 2 frases.
    - Seja humano, claro e util.
    - Tom: {tom}.
    - Se o tom for divertido, use humor leve sem exagero.
    - Nao use markdown.
    - Nao invente dados alem dos informados.

    Evento: {evento}
    Dados financeiros: {dados_financeiros}
    """

    try:
        return GeminiClient().generate_text(prompt, fallback)
    except Exception:
        return fallback
