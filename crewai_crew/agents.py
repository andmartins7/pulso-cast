"""
crewai_crew/agents.py
─────────────────────
CrewAI Agent definitions for the Instagram Post Generator crew.

Three specialist agents, each backed by Claude Sonnet 4 via Amazon Bedrock:
  - TrendAnalyst     : interprets the ContextBrief, produces a creative brief
  - Copywriter       : generates caption, hashtags and CTA
  - VisualDirector   : produces a complete visual brief for image production
"""
from __future__ import annotations

import os

from crewai import Agent
from crewai_tools import SerperDevTool
from langchain_anthropic import ChatAnthropic


# ─── LLM factory ─────────────────────────────────────────────────────────────

def _claude(
    temperature: float = 0.7,
    max_tokens: int = 4096,
    model: str = "claude-sonnet-4-5",
) -> ChatAnthropic:
    return ChatAnthropic(
        model=model,
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        max_tokens=max_tokens,
        temperature=temperature,
    )


# ─── Agent factories ──────────────────────────────────────────────────────────

def get_trend_analyst_agent() -> Agent:
    """
    Senior Digital Trend Analyst.
    Reads the ContextBrief and produces a Creative Brief for the Copywriter.
    Uses Serper to validate last-minute trend context if needed.
    """
    return Agent(
        role="Analista Sênior de Tendências Digitais",
        goal=(
            "Interpretar o ContextBrief recebido e extrair os insights mais relevantes "
            "da tendência. Identificar o ângulo narrativo mais impactante para o "
            "público-alvo da marca e produzir um Briefing Criativo estruturado."
        ),
        backstory=(
            "Você tem 10 anos de experiência em social media intelligence e "
            "planejamento de conteúdo. Combina dados quantitativos (trend score, "
            "benchmarks de engajamento) com leitura qualitativa do zeitgeist digital. "
            "Conhece profundamente o comportamento de audiências brasileiras nas "
            "plataformas Meta e sabe traduzir números em narrativas acionáveis."
        ),
        llm=_claude(temperature=0.4),  # lower temp for analytical task
        verbose=True,
        allow_delegation=False,
        tools=[SerperDevTool(n_results=5)],  # for last-minute validation
        max_iter=3,
    )


def get_copywriter_agent() -> Agent:
    """
    Creative Copywriter for Instagram.
    Converts the Creative Brief into a polished caption + hashtag set.
    """
    return Agent(
        role="Redator Criativo de Conteúdo para Instagram",
        goal=(
            "Criar captions de Instagram que combinem a tendência identificada com a "
            "voz da marca. Estrutura: abertura de impacto (gancho), corpo informativo, "
            "CTA claro. Hashtags estratégicas divididas entre caption e primeiro comentário."
        ),
        backstory=(
            "Copywriter com histórico comprovado em campanhas que alcançaram 1M+ de "
            "impressões orgânicas. Especialista em storytelling digital, psicologia de "
            "consumo e ritmo de leitura em dispositivos móveis. Escreve em português "
            "brasileiro: coloquial mas elegante, sem clichês. Conhece as nuances do "
            "algoritmo do Instagram para maximização de engajamento orgânico."
        ),
        llm=_claude(temperature=0.8),  # higher temp for creative task
        verbose=True,
        allow_delegation=False,
        tools=[],
        max_iter=3,
    )


def get_visual_director_agent() -> Agent:
    """
    Digital Art Director.
    Produces a complete visual brief including DALL-E / Midjourney prompt.
    """
    return Agent(
        role="Diretor de Arte Digital",
        goal=(
            "Criar um Visual Brief completo e detalhado para a produção da imagem "
            "ou vídeo do post. O brief deve ser executável por qualquer designer "
            "ou ferramenta de IA generativa sem ambiguidades."
        ),
        backstory=(
            "Designer com 8 anos de foco em identidade visual para redes sociais. "
            "Domina as especificações técnicas do Instagram (proporções, safe zones, "
            "limites de texto sobre imagem). Combina tendências estéticas atuais com "
            "consistência de branding. Produz prompts de IA generativa que geram "
            "resultados alinhados ao tom e à identidade visual da marca na primeira tentativa."
        ),
        llm=_claude(temperature=0.6),
        verbose=True,
        allow_delegation=False,
        tools=[],
        max_iter=3,
    )
