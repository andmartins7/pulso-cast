"""
guardrails_musicoterapia.py
───────────────────────────
Camada de guardrails éticos específica para publicações de Musicoterapia.

Baseada em:
  - Código Nacional de Ética, Orientação e Disciplina do Musicoterapeuta — UBAM (2018)
  - Diretrizes e Orientações Éticas para Musicoterapeutas — ABMT (2025)
  - Lei Federal 14.842/2024
  - LGPD — Lei nº 13.709/2018

Esta camada é inserida no pipeline TrendCast ANTES da publicação,
após a geração do PostOutput pelo CrewAI.

Uso no pipeline:
    from guardrails_musicoterapia import MusicoterapiaGuardrail, GuardrailViolation
    result = MusicoterapiaGuardrail.validate(post_output)
    if not result.approved:
        # Rejeitar e reenviar ao CrewAI com feedback
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Violation levels ─────────────────────────────────────────────────────────

class Severity:
    BLOCK   = "BLOCK"    # Post não pode ser publicado — violação ética grave
    WARN    = "WARN"     # Publicável, mas requer revisão humana obrigatória
    SUGGEST = "SUGGEST"  # Sugestão de melhoria — não bloqueia


@dataclass
class GuardrailViolation:
    severity:    str
    rule_ref:    str         # ex: "UBAM Art. 52" ou "ABMT Seção 5"
    description: str
    excerpt:     str = ""    # trecho do caption que disparou a regra


@dataclass
class GuardrailResult:
    approved:       bool
    must_review:    bool                          = False
    violations:     list[GuardrailViolation]      = field(default_factory=list)
    suggestions:    list[str]                     = field(default_factory=list)
    sanitized_caption: Optional[str]              = None

    @property
    def blocks(self) -> list[GuardrailViolation]:
        return [v for v in self.violations if v.severity == Severity.BLOCK]

    @property
    def warnings(self) -> list[GuardrailViolation]:
        return [v for v in self.violations if v.severity == Severity.WARN]


# ─── Pattern tables ───────────────────────────────────────────────────────────

# Termos que prometem cura — UBAM Art. 49 + ABMT Seção 5
CURE_PATTERNS = re.compile(
    r"\b(cura(?:r|do|da|ção)?|cure|curei|curou|tratamento definitivo|"
    r"elimina(?:r|ndo)?\ a\ doença|resolve definitivamente|"
    r"acabar? com (?:a|o) \w+|música (?:cura|trata|elimina))\b",
    re.IGNORECASE,
)

# Termos que identificam pacientes — UBAM Art. 16, 52 + LGPD
PATIENT_ID_PATTERNS = re.compile(
    r"\b((?:paciente|cliente|usuário)\s+[A-Z][a-zA-Z]+|"
    r"(?:o|a)\s+(?:sr\.|sra\.|senhor|senhora)\s+[A-Z]|"
    r"\d{1,2}\s+anos.*(?:diagnóstico|tem|possui)\s+|"
    r"(?:leito|quarto|enfermaria)\s+\d+.*(?:paciente|ele|ela))\b",
    re.IGNORECASE,
)

# Uso indevido de título acadêmico — ABMT Seção 3
TITLE_MISUSE_PATTERNS = re.compile(
    r"\b(Dr\.\s+|Dra\.\s+|Dr\s+|Dra\s+|Doutor\s+|Doutora\s+|"
    r"Me\.\s+|Ma\.\s+|Mestre\s+|Mestra\s+)",
    re.IGNORECASE,
)

# Garantias de resultado — UBAM Art. 49 + ABMT Seção 5
GUARANTEE_PATTERNS = re.compile(
    r"\b(garanti(?:r|do|da|mos|a)|100%\s+eficaz|resultados garantidos|"
    r"sempre funciona|nunca falha|comprovadamente cura|"
    r"científicamente provado que (?:cura|trata))\b",
    re.IGNORECASE,
)

# Confusão com outras profissões — ABMT Seção 2
PROFESSION_CONFUSION_PATTERNS = re.compile(
    r"\b(psicóloga?\s*e\s*musicoterapeuta|"
    r"musicoterapeuta\s*e\s*psicóloga?|"
    r"fonoaudióloga?\s*e\s*musicoterapeuta|"
    r"terapeuta\s+ocupacional\s*e\s*musicoterapeuta)\b",
    re.IGNORECASE,
)

# Divulgação de preço como captação — UBAM Art. 49a + ABMT Seção 6
PRICE_AS_PROMO_PATTERNS = re.compile(
    r"\b(sessão\s+por\s+R\$|apenas\s+R\$\s*\d+|a\s+partir\s+de\s+R\$|"
    r"planos?\s+a\s+partir|pacotes?\s+especiais?.*musicoterapia|"
    r"primeira\s+sessão\s+gr[aá]tis)\b",
    re.IGNORECASE,
)

# Equiparação inadequada (musicoterapia como lazer ou aula)
LAZER_PATTERNS = re.compile(
    r"\b(aula de música|recreação|lazer|entretenimento|"
    r"apenas\s+tocar\s+música|só\s+(?:ouvir|cantar)|diversão terapêutica)\b",
    re.IGNORECASE,
)

# Obrigatoriedade de identificação profissional — UBAM Art. 48 + ABMT Seção 1
ID_PROFESSIONAL_PATTERN = re.compile(
    r"Mt\.\s+\w+",
    re.IGNORECASE,
)

# Indicadores de relato de caso (requerem validação de anonimização)
CASE_REPORT_TRIGGERS = re.compile(
    r"\b(paciente|caso clínico|relato de caso|numa sessão|"
    r"durante o atendimento|estava internado|ela disse|ele disse|"
    r"a família relatou|os responsáveis contaram)\b",
    re.IGNORECASE,
)


# ─── Main guardrail class ─────────────────────────────────────────────────────

class MusicoterapiaGuardrail:
    """
    Validador ético de posts de Musicoterapia para o TrendCast.

    Método principal: MusicoterapiaGuardrail.validate(caption, full_text)
    """

    @classmethod
    def validate(
        cls,
        caption: str,
        full_text: str = "",
        has_patient_authorization: bool = False,
        professional_title_verified: bool = False,
    ) -> GuardrailResult:
        """
        Valida um post gerado pelo CrewAI contra os parâmetros éticos.

        Args:
            caption:                     Texto completo do caption.
            full_text:                   Texto adicional (visual brief description etc.).
            has_patient_authorization:   True se há TCLE assinado (relatos de caso).
            professional_title_verified: True se título acadêmico (Dr./Me.) foi verificado.

        Returns:
            GuardrailResult com approved, violações e sugestões.
        """
        violations: list[GuardrailViolation] = []
        suggestions: list[str] = []
        text = f"{caption} {full_text}".strip()

        # ── BLOCK rules ───────────────────────────────────────────────────────

        # 1. Linguagem de cura
        if match := CURE_PATTERNS.search(text):
            violations.append(GuardrailViolation(
                severity=Severity.BLOCK,
                rule_ref="UBAM Art. 49 + ABMT Seção 5",
                description="Uso de linguagem que promete ou sugere cura pela música. "
                            "Substitua por: 'promove bem-estar', 'apoia a reabilitação', "
                            "'contribui para a regulação emocional'.",
                excerpt=match.group(),
            ))

        # 2. Identificação de paciente
        if match := PATIENT_ID_PATTERNS.search(text):
            violations.append(GuardrailViolation(
                severity=Severity.BLOCK,
                rule_ref="UBAM Art. 16 + Art. 52 + LGPD",
                description="Possível identificação de paciente detectada. "
                            "Anonimize completamente: remova nome, quarto, diagnóstico identificador "
                            "e qualquer combinação de dados que possa singularizar o indivíduo.",
                excerpt=match.group(),
            ))

        # 3. Garantias de resultado
        if match := GUARANTEE_PATTERNS.search(text):
            violations.append(GuardrailViolation(
                severity=Severity.BLOCK,
                rule_ref="UBAM Art. 49 + ABMT Seção 5",
                description="Linguagem de garantia de resultado não é permitida. "
                            "Substitua por: 'evidências indicam', 'estudos mostram', "
                            "'pode contribuir para'.",
                excerpt=match.group(),
            ))

        # 4. Preço como propaganda
        if match := PRICE_AS_PROMO_PATTERNS.search(text):
            violations.append(GuardrailViolation(
                severity=Severity.BLOCK,
                rule_ref="UBAM Art. 49a + ABMT Seção 6",
                description="Divulgação de preço como forma de captação é vedada. "
                            "Honorários devem ser comunicados diretamente ao contratante/paciente.",
                excerpt=match.group(),
            ))

        # ── WARN rules ────────────────────────────────────────────────────────

        # 5. Relato de caso sem autorização
        if CASE_REPORT_TRIGGERS.search(text) and not has_patient_authorization:
            violations.append(GuardrailViolation(
                severity=Severity.WARN,
                rule_ref="UBAM Art. 16 + Art. 43 + Art. 52",
                description="Post aparenta conter relato de caso clínico. "
                            "Verifique: (a) se há TCLE assinado, (b) se todos os dados "
                            "identificadores foram removidos, (c) se a motivação da "
                            "divulgação beneficia a profissão sem expor o paciente.",
            ))

        # 6. Confusão com outras profissões
        if match := PROFESSION_CONFUSION_PATTERNS.search(text):
            violations.append(GuardrailViolation(
                severity=Severity.WARN,
                rule_ref="ABMT Seção 2",
                description="Divulgação conjunta de musicoterapia com outra profissão. "
                            "Perfis e posts devem ser exclusivos da musicoterapia para "
                            "evitar confusão pública sobre a identidade profissional.",
                excerpt=match.group(),
            ))

        # 7. Uso de título acadêmico não verificado
        if TITLE_MISUSE_PATTERNS.search(text) and not professional_title_verified:
            violations.append(GuardrailViolation(
                severity=Severity.WARN,
                rule_ref="ABMT Seção 3",
                description="Título acadêmico (Dr./Me.) detectado. "
                            "Confirme que a profissional possui o título com diploma "
                            "validado em território brasileiro antes de publicar.",
            ))

        # 8. Equiparação à aula de música ou lazer
        if match := LAZER_PATTERNS.search(text):
            violations.append(GuardrailViolation(
                severity=Severity.WARN,
                rule_ref="UBAM Art. 20 + Art. 35",
                description="Linguagem que pode confundir musicoterapia com lazer ou "
                            "aula de música. A musicoterapia é um processo terapêutico "
                            "com objetivos funcionais — não recreação.",
                excerpt=match.group(),
            ))

        # ── SUGGEST rules ─────────────────────────────────────────────────────

        # 9. Ausência de identificação profissional
        if not ID_PROFESSIONAL_PATTERN.search(text):
            suggestions.append(
                "Inclua a identificação profissional ao final: "
                "'Mt. [Nome Completo] — Musicoterapeuta ([Nº de registro])' "
                "(UBAM Art. 48a + ABMT Seção 1)."
            )

        # 10. Ausência de referência científica em post técnico
        has_technical_terms = bool(re.search(
            r"\b(ansiedade|dor|cognição|neuroplasticidade|reabilitação|"
            r"UTI|paliativo|Alzheimer|Parkinson|TEA|TDAH)\b",
            text, re.IGNORECASE,
        ))
        has_reference = bool(re.search(
            r"\b(estudo|pesquisa|evidências?|revisão|publicado|DOI|"
            r"segundo|de acordo com)\b",
            text, re.IGNORECASE,
        ))
        if has_technical_terms and not has_reference:
            suggestions.append(
                "Post aborda tema técnico sem referência científica. "
                "Considere citar uma pesquisa ou estudo de forma acessível "
                "para fortalecer a credibilidade profissional (UBAM Art. 35)."
            )

        # ── Build result ──────────────────────────────────────────────────────
        has_blocks   = any(v.severity == Severity.BLOCK   for v in violations)
        has_warnings = any(v.severity == Severity.WARN    for v in violations)

        result = GuardrailResult(
            approved=not has_blocks,
            must_review=has_warnings,
            violations=violations,
            suggestions=suggestions,
        )

        if has_blocks:
            logger.warning(
                f"Post BLOQUEADO por guardrail ético | "
                f"violações={len(result.blocks)} | "
                f"refs={[v.rule_ref for v in result.blocks]}"
            )
        elif has_warnings:
            logger.info(
                f"Post aprovado COM REVISÃO OBRIGATÓRIA | "
                f"avisos={len(result.warnings)}"
            )
        else:
            logger.info("Post aprovado pelos guardrails éticos de musicoterapia")

        return result


# ─── CrewAI task integration helper ──────────────────────────────────────────

def build_guardrail_feedback(result: GuardrailResult) -> str:
    """
    Formata o feedback dos guardrails como prompt de correção
    para ser reinjetado no agente Copywriter do CrewAI.
    """
    if result.approved and not result.must_review:
        return ""

    lines = [
        "⚠️ FEEDBACK ÉTICO — O post gerado precisa ser corrigido antes da publicação:\n"
    ]

    for i, v in enumerate(result.violations, 1):
        icon = "🚫" if v.severity == Severity.BLOCK else "⚠️"
        lines.append(f"{icon} [{v.rule_ref}] {v.description}")
        if v.excerpt:
            lines.append(f"   Trecho problemático: '{v.excerpt}'")
        lines.append("")

    if result.suggestions:
        lines.append("💡 SUGESTÕES:")
        for s in result.suggestions:
            lines.append(f"   • {s}")

    lines.append(
        "\nReescreva o caption corrigindo todos os pontos acima. "
        "Mantenha o tom humanizado e acolhedor. "
        "Não use linguagem de cura. Não identifique pacientes."
    )

    return "\n".join(lines)


# ─── Lambda handler ───────────────────────────────────────────────────────────

def lambda_handler(event: dict, context) -> dict:
    """
    Entry-point Lambda para o Step Functions EthicsGuardrail.

    Event: {
        "post_output":   PostOutput dict,
        "requires_tcle": bool,
        "show_epi":      bool
    }
    Returns: {
        "approved":     bool,
        "must_review":  bool,
        "violations":   list,
        "feedback":     str,
        "status":       "ok"
    }
    """
    post_output  = event.get("post_output", {})
    requires_tcle = bool(event.get("requires_tcle", False))
    # show_epi is informational — handled by CrewAI/image-gen

    caption   = post_output.get("caption", "")
    image_prompt = post_output.get("visual_brief", {}).get("image_prompt", "") if isinstance(post_output.get("visual_brief"), dict) else ""
    full_text = image_prompt

    # requires_tcle=True means content may identify a patient → treat as unauthorized
    result = MusicoterapiaGuardrail.validate(
        caption=caption,
        full_text=full_text,
        has_patient_authorization=(not requires_tcle),
    )

    return {
        "approved":    result.approved,
        "must_review": result.must_review,
        "violations":  [
            {
                "severity":    v.severity,
                "rule_ref":    v.rule_ref,
                "description": v.description,
                "excerpt":     v.excerpt,
            }
            for v in result.violations
        ],
        "feedback": build_guardrail_feedback(result),
        "status":   "ok",
    }
