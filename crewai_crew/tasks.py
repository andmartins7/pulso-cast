"""
crewai_crew/tasks_musicoterapia_hospitalar.py
─────────────────────────────────────────────
Tasks especializadas para geração de conteúdo de Musicoterapia Hospitalar.

Substituem as tasks genéricas do pipeline TrendCast para este nicho.
Cada task embutem o contexto ético e clínico diretamente no prompt.

Uso:
    from tasks_musicoterapia_hospitalar import (
        get_analyst_task_mt,
        get_copywriter_task_mt,
        get_visual_task_mt,
    )
"""
from __future__ import annotations

from crewai import Agent, Task
from schemas import ContextBrief


# ─── TASK 1 — Analista de Tendências (especializado MT Hospitalar) ────────────

def get_analyst_task_mt(agent: Agent, brief: ContextBrief) -> Task:
    """
    Analisa a tendência sob a ótica da musicoterapia hospitalar.
    Output: Briefing Criativo com ângulo clínico, pilar de conteúdo e setor.
    """
    brief_json  = brief.model_dump_json(indent=2)
    trend_topic = brief.trend_context.topic
    trend_score = brief.trend_context.trend_score
    audience    = brief.brand_context.target_audience

    return Task(
        description=f"""
        Você é Analista Sênior de Conteúdo em Saúde e Musicoterapia Hospitalar.
        Recebeu o seguinte ContextBrief:

        ```json
        {brief_json}
        ```

        Sua tarefa é produzir um **Briefing Criativo Clínico** que responda:

        ──────────────────────────────────────────────────────
        SEÇÃO 1 — QUAL PILAR DE CONTEÚDO?
        Classifique a tendência '{trend_topic}' (score: {trend_score:.2f}) em um dos 5 pilares:
          • Pilar 1 — A Ciência Atrás do Som (neurociência, evidências, biomarcadores)
          • Pilar 2 — Humanização no Leito (relato humano, vínculo, impacto emocional)
          • Pilar 3 — Por Trás das Notas (bastidores éticos, instrumentos, rotina profissional)
          • Pilar 4 — Mito x Verdade (desmistificação, educação do público)
          • Pilar 5 — Setor Hospitalar específico (UTI, Oncologia, Paliativo, Neonatal, Saúde Mental)
        Justifique a escolha.

        SEÇÃO 2 — QUAL SETOR HOSPITALAR?
        Esta tendência se conecta melhor a qual setor?
          UTI · Oncologia Pediátrica · Cuidados Paliativos · Maternidade/UTIN ·
          Reabilitação Neurológica · Saúde Mental/Psiquiatria · Geral
        Justifique.

        SEÇÃO 3 — ÂNGULO NARRATIVO
        Qual é a HISTÓRIA que vamos contar? Qual tensão ou pergunta captura atenção?
        Exemplo de bom ângulo: "A música faz o cortisol cair 12%. Isso não é poesia — é bioquímica."
        Exemplo de ângulo PROIBIDO: "A música cura a dor" — não usamos linguagem de cura.

        SEÇÃO 4 — GANCHO DA PRIMEIRA LINHA
        Escreva 3 opções de abertura para o caption (máx. 15 palavras cada).
        REGRA: nunca começar com "Você sabia que...".
        Opções válidas: dado científico direto / cena humana anonimizada / pergunta que o público não sabe responder.

        SEÇÃO 5 — ÂNCORAS CIENTÍFICAS
        Liste 2-3 dados ou estudos que DEVEM aparecer no post se o pilar for "Ciência".
        Se pilar for "Humanização" ou "Bastidores", liste os elementos emocionais ou visuais principais.

        SEÇÃO 6 — GUARDRAILS ÉTICOS PARA ESTE POST
        Identifique os riscos éticos específicos para ESTE ângulo:
          • Há risco de identificação de paciente? Como evitar?
          • Há risco de promessa de cura? Qual linguagem usar no lugar?
          • O conteúdo exige autorização prévia (TCLE)? Para quê?
          • O musicoterapeuta deve aparecer com jaleco/crachá/EPI? Por quê?
        ──────────────────────────────────────────────────────

        AUDIÊNCIA DO POST: {audience}
        """,
        agent=agent,
        expected_output=(
            "Briefing Criativo Clínico em 6 seções, em português do Brasil. "
            "400–600 palavras. Pilar e setor claramente definidos. "
            "Guardrails éticos específicos para o conteúdo."
        ),
    )


# ─── TASK 2 — Copywriter (especializado MT Hospitalar) ───────────────────────

def get_copywriter_task_mt(
    agent: Agent,
    brief: ContextBrief,
    analyst_task: Task,
) -> Task:
    """
    Redige o caption completo para o setor e pilar identificados.
    Integra guardrails éticos diretamente no prompt.
    """
    req    = brief.post_requirements
    brand  = brief.brand_context
    fmt    = req.format.value.upper()
    lang   = req.language

    return Task(
        description=f"""
        Com base no Briefing Criativo Clínico (task anterior), redija o post completo.

        FORMATO: {fmt}
        IDIOMA: {lang}
        LIMITE: {req.caption_max_chars} caracteres
        HASHTAGS NO CAPTION: máx. {req.max_hashtags_in_caption}
        CTA: obrigatório
        EMOJIS: sim, com moderação — apenas quando reforçam o significado clínico

        ──────────────────────────────────────────────────────
        REGRAS DE ESCRITA PARA MUSICOTERAPIA HOSPITALAR:

        ESTRUTURA OBRIGATÓRIA:
          1. GANCHO (linha 1) — dado científico / cena humana anonimizada / pergunta
             PROIBIDO: "Você sabia que..." | "Incrível como..." | frases genéricas
          2. CORPO — educação, humanização ou bastidores (conforme pilar)
             Use parágrafos curtos com linha em branco entre eles
             Máx. 3-4 parágrafos
          3. ENCERRAMENTO — posicionamento profissional (1-2 frases)
          4. IDENTIFICAÇÃO: "Mt. [Nome] — Musicoterapeuta" (obrigatório)
          5. CTA — pergunta, convite para salvar ou compartilhar com equipe

        LINGUAGEM PROIBIDA (erros éticos graves):
          ❌ "cura" / "música cura" / "curou" / "tratamento definitivo"
          ❌ "garante" / "100% eficaz" / "sempre funciona"
          ❌ Nome / quarto / diagnóstico que identifique paciente
          ❌ Preço de sessão
          ❌ "Dr." / "Me." sem ter o título

        LINGUAGEM RECOMENDADA:
          ✅ "evidências indicam" / "estudos mostram" / "contribui para"
          ✅ "apoia a reabilitação" / "promove bem-estar"
          ✅ "de acordo com pesquisas em..." / "uma revisão sistemática de..."
          ✅ Se relato de caso: "[Relato anonimizado. Autorização obtida dos familiares. UBAM Art. 52.]"

        PROFISSIONALISMO VISUAL NO TEXTO:
          - Se for REEL com bastidores: mencionar jaleco, crachá, EPI quando relevante
          - Se for relato: mencionar que a musicoterapeuta atuou dentro do prontuário,
            com objetivos e avaliação documentados

        VÍNCULO COM EQUIPE MULTIPROFISSIONAL (sempre que possível):
          - A musicoterapia não trabalha isolada — referenciar médicos, enfermagem,
            fisio, psicologia como parceiros de cuidado
        ──────────────────────────────────────────────────────

        VOZ DA MARCA: {brand.brand_voice}
        DIRETRIZES: {brand.content_guidelines[:500]}...

        RETORNE APENAS O JSON:
        {{
          "caption": "texto completo com emojis e quebras de linha",
          "hashtags_no_caption": ["#tag1", "#tag2"],
          "hashtags_primeiro_comentario": ["#tag3", "#tag4"],
          "cta": "chamada isolada sem hashtag",
          "char_count": 0,
          "pilar_identificado": "nome do pilar",
          "setor_identificado": "setor hospitalar",
          "justificativa_etica": "como este post respeita os guardrails"
        }}
        """,
        agent=agent,
        context=[analyst_task],
        expected_output=(
            "JSON válido com caption completo, hashtags, CTA, pilar, setor "
            "e justificativa ética do post."
        ),
    )


# ─── TASK 3 — Diretor Visual (especializado MT Hospitalar) ───────────────────

def get_visual_task_mt(
    agent: Agent,
    brief: ContextBrief,
    copywriter_task: Task,
) -> Task:
    """
    Cria o Visual Brief clínico para o post — priorizando ambiente hospitalar
    real, profissionalismo visual (jaleco, EPI) e ausência de identificação de pacientes.
    """
    fmt   = brief.post_requirements.format.value
    brand = brief.brand_context

    aspect_map = {
        "feed":     "4:5 (1080×1350 px)",
        "story":    "9:16 (1080×1920 px)",
        "reel":     "9:16 (1080×1920 px)",
        "carousel": "4:5 por slide",
    }
    aspect = aspect_map.get(fmt, "4:5")

    return Task(
        description=f"""
        Com base no caption gerado (task anterior) e no ContextBrief,
        crie um **Visual Brief Clínico** para a produção da imagem/vídeo.

        FORMATO: {fmt}
        PROPORÇÃO: {aspect}
        MARCA: {brand.brand_name}
        VALORES: {", ".join(brand.brand_values)}

        ──────────────────────────────────────────────────────
        REGRAS VISUAIS PARA MUSICOTERAPIA HOSPITALAR:

        PROFISSIONALISMO:
          - Musicoterapeuta SEMPRE com jaleco (branco ou colorido) e crachá visível
          - Se setor exigir EPI: mostrar usando — isso reforça credibilidade clínica
          - Sem figurino casual ou artístico — é profissional de saúde, não performer

        AMBIENTE:
          - Ambiente hospitalar REAL é bem-vindo: corredor, leito vazio, sala terapêutica
          - Evitar produção excessivamente "spa" ou "sala de meditação" — não é esse o contexto
          - Instrumentos sobre superfícies clínicas (bancada, mesinha de leito) têm apelo autêntico

        PACIENTES:
          - NUNCA mostrar rosto de paciente sem TCLE documentado
          - Se TCLE existe: enquadrar de forma que não seja identificável
            (costas, mãos, detalhe do instrumento, etc.)
          - Preferir: mãos do terapeuta + instrumento, sem paciente em cena

        INSTRUMENTOS:
          - Devem ser reais e hospitalares: kalimba, xilofone terapêutico,
            chocalho de leito, ocean drum, violão com silenciador
          - Evitar: teclado grandioso, bateria, instrumentos de "show"

        PALETA DE CORES:
          - Azul-clínico + branco: autoridade técnica
          - Verde-menta + branco: humanização e cuidado
          - Terracota suave + bege: calor humano paliativo
          - EVITAR: neon, paleta muito saturada (parece entretenimento)

        TEXTO NA IMAGEM:
          - Se houver overlay: máx. 20% da área
          - Tipografia limpa, sem fontes cursivas decorativas
          - Dados ou frases-chave podem aparecer em destaque
        ──────────────────────────────────────────────────────

        RETORNE APENAS O JSON:
        {{
          "primary_color_palette": ["#HEX ou nome descritivo"],
          "visual_style": "descrição em 1 frase",
          "image_prompt": "prompt DETALHADO em inglês para DALL-E 3 / Midjourney (mín. 60 palavras). OBRIGATÓRIO: incluir jaleco branco, hospital setting, no patient face, clinical instruments. NÃO incluir: smiling patient, spa, meditation room.",
          "format_specs": {{
            "aspect_ratio": "{aspect}",
            "text_overlay": "true/false",
            "text_overlay_content": "texto se aplicável",
            "epi_required": "true/false — se EPI deve aparecer na imagem",
            "safe_zone_notes": "posicionamento para Instagram"
          }},
          "mood_references": ["ref 1", "ref 2"],
          "production_notes": "o que EVITAR. O que reforça credibilidade clínica."
        }}
        """,
        agent=agent,
        context=[copywriter_task],
        expected_output=(
            "JSON válido com visual brief clínico: paleta, estilo, prompt IA (≥60 palavras em inglês), "
            "specs técnicas com indicação de EPI e ausência de paciente identificado."
        ),
    )
