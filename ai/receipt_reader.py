from datetime import date

from ai.gemini_client import GeminiClient


def ler_comprovante(caminho_imagem):
    fallback = {
        "valor": 89.90,
        "data": date.today().isoformat(),
        "favorecido": "Vivo",
        "tipo_pagamento": "Pix",
        "categoria_provavel": "Celular",
        "descricao": "Pagamento identificado em comprovante",
        "modo": "simulado",
    }

    prompt = """
    Analise este comprovante brasileiro e retorne apenas JSON valido, sem markdown.

    Campos obrigatorios:
    valor: numero
    data: yyyy-mm-dd ou null
    favorecido: texto
    tipo_pagamento: Pix, boleto, cartao, transferencia, dinheiro ou desconhecido
    categoria_provavel: Salario, Alimentacao, Moradia, Transporte, Celular, Lazer ou Outros
    descricao: resumo curto
    """
    return GeminiClient().generate_json_from_image(prompt, caminho_imagem, fallback)
