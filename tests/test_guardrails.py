"""
Ethics guardrail tests — MusicoterapiaGuardrail + lambda_handler.

Covers BLOCK rules (cure language, guarantees, patient ID, price promo),
WARN rules (case reports, profession confusion), and the Lambda contract.
"""
from __future__ import annotations

import pytest

from guardrails_musicoterapia import (
    GuardrailResult,
    GuardrailViolation,
    MusicoterapiaGuardrail,
    Severity,
    build_guardrail_feedback,
    lambda_handler,
)


# ─── BLOCK rules ──────────────────────────────────────────────────────────────

class TestCureLanguageBlocked:
    @pytest.mark.parametrize("text", [
        "A música cura a depressão",
        "musicoterapia pode curar o câncer",
        "essa técnica cura a ansiedade",
        "tratamento definitivo para insônia",
        "música cura qualquer doença",
    ])
    def test_cure_language_blocks(self, text: str):
        result = MusicoterapiaGuardrail.validate(text)
        assert not result.approved, f"Expected BLOCK for: {text!r}"
        assert any(v.severity == Severity.BLOCK for v in result.violations)

    def test_block_violation_includes_rule_ref(self):
        result = MusicoterapiaGuardrail.validate("a música cura tudo")
        blocks = result.blocks
        assert len(blocks) > 0
        assert all(v.rule_ref for v in blocks)


class TestGuaranteeLanguageBlocked:
    @pytest.mark.parametrize("text", [
        "Este protocolo garante resultados",
        "100% eficaz para reduzir a dor",
        "resultados garantidos em 30 dias",
        "comprovadamente cura a fibromialgia",
    ])
    def test_guarantee_blocks(self, text: str):
        result = MusicoterapiaGuardrail.validate(text)
        assert not result.approved, f"Expected BLOCK for: {text!r}"


class TestPricePromoBlocked:
    @pytest.mark.parametrize("text", [
        "Sessão por R$ 150 — agende já!",
        "apenas R$ 80 por atendimento",
        "primeira sessão grátis de musicoterapia!",
        "planos a partir de R$ 200",
    ])
    def test_price_promo_blocks(self, text: str):
        result = MusicoterapiaGuardrail.validate(text)
        assert not result.approved, f"Expected BLOCK for: {text!r}"


# ─── WARN rules ───────────────────────────────────────────────────────────────

class TestCaseReportWarning:
    def test_case_report_without_authorization_warns(self):
        text = "Numa sessão, o paciente relatou melhora significativa na dor."
        result = MusicoterapiaGuardrail.validate(text, has_patient_authorization=False)
        assert result.must_review
        assert any(v.severity == Severity.WARN for v in result.violations)

    def test_case_report_with_authorization_no_warn(self):
        text = "Numa sessão, o paciente relatou melhora na dor."
        result = MusicoterapiaGuardrail.validate(text, has_patient_authorization=True)
        case_warns = [
            v for v in result.violations
            if v.severity == Severity.WARN and "relato" in v.description.lower()
        ]
        assert not case_warns

    def test_approved_with_must_review_is_possible(self):
        """A post can be approved (no BLOCK) but require human review (WARN)."""
        text = "Numa sessão, o paciente relatou melhora na dor."
        result = MusicoterapiaGuardrail.validate(text, has_patient_authorization=False)
        assert result.must_review
        # Still approved if no BLOCK violations
        assert result.approved


class TestProfessionConfusionWarning:
    def test_dual_profession_warns(self):
        text = "Sou psicóloga e musicoterapeuta, atuando em contexto hospitalar."
        result = MusicoterapiaGuardrail.validate(text)
        assert result.must_review


# ─── Approved cases ───────────────────────────────────────────────────────────

class TestCleanTextApproved:
    @pytest.mark.parametrize("text", [
        "Evidências indicam que a musicoterapia contribui para a regulação emocional.",
        "A musicoterapia apoia a reabilitação neurológica com base em evidências científicas.",
        "Estudos mostram redução do estresse em pacientes de UTI com intervenção musical.",
        "A musicoterapia promove bem-estar e qualidade de vida em cuidados paliativos.",
    ])
    def test_evidence_language_approved(self, text: str):
        result = MusicoterapiaGuardrail.validate(text)
        assert result.approved, f"Unexpected block for: {text!r}"
        assert not result.blocks

    def test_empty_caption_approved(self):
        result = MusicoterapiaGuardrail.validate("")
        assert result.approved
        assert not result.violations

    def test_approved_must_review_false_when_clean(self):
        text = "A musicoterapia apoia a reabilitação. Evidências indicam melhora."
        result = MusicoterapiaGuardrail.validate(text)
        assert result.approved
        assert not result.must_review


# ─── GuardrailResult helpers ──────────────────────────────────────────────────

class TestGuardrailResultHelpers:
    def test_blocks_property_filters_by_severity(self):
        result = GuardrailResult(
            approved=False,
            violations=[
                GuardrailViolation(severity=Severity.BLOCK, rule_ref="A", description="d"),
                GuardrailViolation(severity=Severity.WARN,  rule_ref="B", description="d"),
            ],
        )
        assert len(result.blocks) == 1
        assert len(result.warnings) == 1

    def test_warnings_property_filters_by_severity(self):
        result = GuardrailResult(
            approved=True,
            must_review=True,
            violations=[
                GuardrailViolation(severity=Severity.WARN, rule_ref="A", description="d"),
            ],
        )
        assert len(result.warnings) == 1
        assert len(result.blocks) == 0


# ─── build_guardrail_feedback ─────────────────────────────────────────────────

class TestBuildGuardrailFeedback:
    def test_clean_result_returns_empty_string(self):
        result = GuardrailResult(approved=True, must_review=False)
        assert build_guardrail_feedback(result) == ""

    def test_blocked_result_returns_actionable_feedback(self):
        result = GuardrailResult(
            approved=False,
            violations=[
                GuardrailViolation(
                    severity=Severity.BLOCK,
                    rule_ref="UBAM Art. 49",
                    description="Linguagem de cura detectada.",
                    excerpt="cura",
                )
            ],
        )
        feedback = build_guardrail_feedback(result)
        assert len(feedback) > 0
        assert "UBAM Art. 49" in feedback
        assert "cura" in feedback

    def test_feedback_contains_rewrite_instruction(self):
        result = GuardrailResult(
            approved=False,
            violations=[
                GuardrailViolation(severity=Severity.BLOCK, rule_ref="X", description="d")
            ],
        )
        feedback = build_guardrail_feedback(result)
        assert "Reescreva" in feedback


# ─── Lambda handler contract ──────────────────────────────────────────────────

class TestGuardrailsLambdaHandler:
    def test_returns_all_required_keys(self, minimal_post_output):
        event = {
            "post_output": minimal_post_output.model_dump(mode="json"),
            "requires_tcle": False,
            "show_epi": False,
        }
        result = lambda_handler(event, None)
        for key in ("approved", "must_review", "violations", "feedback", "status"):
            assert key in result, f"Missing key: {key}"

    def test_status_is_ok(self, minimal_post_output):
        event = {
            "post_output": minimal_post_output.model_dump(mode="json"),
            "requires_tcle": False,
            "show_epi": False,
        }
        assert lambda_handler(event, None)["status"] == "ok"

    def test_clean_caption_approved(self, minimal_post_output):
        event = {
            "post_output": minimal_post_output.model_dump(mode="json"),
            "requires_tcle": False,
            "show_epi": False,
        }
        assert lambda_handler(event, None)["approved"] is True

    def test_violations_is_list(self, minimal_post_output):
        event = {
            "post_output": minimal_post_output.model_dump(mode="json"),
            "requires_tcle": False,
            "show_epi": False,
        }
        result = lambda_handler(event, None)
        assert isinstance(result["violations"], list)

    def test_empty_event_does_not_crash(self):
        result = lambda_handler({}, None)
        assert result["status"] == "ok"
        assert result["approved"] is True

    def test_requires_tcle_with_case_report_warns(self, minimal_post_output):
        """requires_tcle=True + case-report language → must_review=True."""
        post = minimal_post_output.model_copy(
            update={"caption": "Numa sessão, o paciente relatou melhora."}
        )
        event = {
            "post_output": post.model_dump(mode="json"),
            "requires_tcle": True,
            "show_epi": False,
        }
        result = lambda_handler(event, None)
        assert result["must_review"] is True

    def test_each_violation_has_required_fields(self, minimal_post_output):
        post = minimal_post_output.model_copy(
            update={"caption": "A música cura a depressão. Garante resultados."}
        )
        event = {
            "post_output": post.model_dump(mode="json"),
            "requires_tcle": False,
            "show_epi": False,
        }
        result = lambda_handler(event, None)
        for v in result["violations"]:
            assert "severity" in v
            assert "rule_ref" in v
            assert "description" in v
