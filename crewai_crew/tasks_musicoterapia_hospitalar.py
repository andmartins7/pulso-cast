"""
crewai_crew/tasks_musicoterapia_hospitalar.py
─────────────────────────────────────────────
Tasks especializadas para geração de conteúdo de Musicoterapia Hospitalar.
"""
from __future__ import annotations

from crewai import Agent, Task
from schemas import ContextBrief


# ─── TASK 1 — Analista de Tendências ─────────────────────────────────────────

def get_analyst_task_mt(agent: Agent, brief: ContextBrief) -> Task:
    brief_json  = brief.model_dump_json(indent=2)
    trend_topic = brief.trend_context.topic
    trend_score = brief.trend_context.trend_score
    audience    = brief.brand_identity.target_audience

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


# ─── TASK 2 — Copywriter ─────────────────────────────────────────────────────

def get_copywriter_task_mt(
    agent: Agent,
    brief: ContextBrief,
    analyst_task: Task,
) -> Task:
    req   = brief.post_requirements
    brand = brief.brand_identity
    fmt   = req.format.value.upper()
    lang  = req.language
    ethical_context = " | ".join(brand.ethical_frameworks[:3])

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
          4. IDENTIFICAÇÃO: "{brand.professional_id}" (obrigatório)
          5. CTA — pergunta, convite para salvar ou compartilhar com equipe

        LINGUAGEM PROIBIDA (erros éticos graves):
          ❌ {" | ".join(brand.forbidden_language[:6])}
          ❌ Nome / quarto / diagnóstico que identifique paciente
          ❌ Preço de sessão

        LINGUAGEM RECOMENDADA:
          ✅ "evidências indicam" / "estudos mostram" / "contribui para"
          ✅ "apoia a reabilitação" / "promove bem-estar"
          ✅ Se relato de caso: "{brand.required_disclaimers.get('case_report', '[Relato anonimizado. UBAM Art. 52.]')}"

        FRAMEWORKS ÉTICOS: {ethical_context}
        VOZ DA MARCA: {brand.brand_voice}

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


# ─── TASK 3 — Diretor Visual ──────────────────────────────────────────────────

def get_visual_task_mt(
    agent: Agent,
    brief: ContextBrief,
    copywriter_task: Task,
) -> Task:
    fmt   = brief.post_requirements.format.value
    brand = brief.brand_identity

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
          - Musicoterapeuta SEMPRE com jaleco e crachá visível
          - Se setor exigir EPI: mostrar usando — reforça credibilidade clínica
          - Sem figurino casual ou artístico

        AMBIENTE:
          - Ambiente hospitalar real é bem-vindo: corredor, leito vazio, sala terapêutica
          - Evitar produção "spa" ou "sala de meditação"
          - Instrumentos sobre superfícies clínicas têm apelo autêntico

        PACIENTES:
          - NUNCA mostrar rosto de paciente sem TCLE documentado
          - Preferir: mãos do terapeuta + instrumento, sem paciente em cena

        INSTRUMENTOS VÁLIDOS:
          - kalimba, xilofone terapêutico, chocalho de leito, ocean drum, violão
          - Evitar: teclado grandioso, bateria, instrumentos de show

        PALETA:
          - Azul-clínico + branco: autoridade técnica
          - Verde-menta + branco: humanização
          - Terracota + bege: calor humano paliativo
        ──────────────────────────────────────────────────────

        RETORNE APENAS O JSON:
        {{
          "primary_color_palette": ["#HEX ou nome descritivo"],
          "visual_style": "descrição em 1 frase",
          "image_prompt": "prompt DETALHADO em inglês para DALL-E 3 (mín. 60 palavras). OBRIGATÓRIO: jaleco branco, hospital setting, no patient face, clinical instruments.",
          "format_specs": {{
            "aspect_ratio": "{aspect}",
            "text_overlay": "true/false",
            "text_overlay_content": "texto se aplicável",
            "epi_required": "true/false",
            "safe_zone_notes": "posicionamento para Instagram"
          }},
          "mood_references": ["ref 1", "ref 2"],
          "production_notes": "o que EVITAR e o que reforça credibilidade clínica."
        }}
        """,
        agent=agent,
        context=[copywriter_task],
        expected_output=(
            "JSON válido com visual brief clínico: paleta, estilo, prompt IA (≥60 palavras em inglês), "
            "specs técnicas com indicação de EPI e ausência de paciente identificado."
        ),
    )
