# PulsoCast — Migration Log

Migrado em: 2026-04-24 23:42:48
Fonte: `C:\projetos\pulso-cast`
Destino: `C:\projetos\pulso-cast\pulsocast`

## Operações realizadas

| Arquivo | Ação | Descrição |
|---|---|---|
| `schemas.py` | ✅ replace | BrandContext → BrandIdentity + ContentStrategyRecommendation. TrendPayload ganha campo content_strategy. Novos enums: ContentPillar, HospitalSector, PostTone clínico. |
| `agno_agent/trend_agent.py` | ✅ replace | Agent agora gera ContentStrategyRecommendation dentro do TrendPayload. Fontes expandidas: PubMed, SciELO, RBMT, WFMT. |
| `bridge/lambda_handler.py` | ✅ replace | Carrega BrandIdentity (não BrandContext). Não decide mais estratégia — usa content_strategy do Agno. SSM path: /trendcast/brand/{id}/context → /pulsocast/brand/{id}/identity. |
| `crewai_crew/tasks.py` | ✅ replace | Tasks reescritas com contexto clínico hospitalar. Guardrails éticos embutidos nos prompts. Analista identifica pilar e setor antes de escrever. |
| `crewai_crew/instagram_crew.py` | ✅ patch | Atualiza import das tasks genéricas → tasks especializadas MT Hospitalar. |
| `guardrails_musicoterapia.py` | ✅ new | Validação ética pós-geração: 10 regras UBAM + ABMT + LGPD. BLOCK / WARN / SUGGEST. Feedback para reescrita pelo CrewAI. |
| `ssm_brand_identity.json` | ✅ new | Template SSM com apenas identidade imutável da marca. Substitui brand_context_musicoterapia.json da v1. |
| `README.md` | ✅ new | README específico do PulsoCast. |
| `agno_agent/__init__.py` | ✅ copy | Inalterado. |
| `bridge/__init__.py` | ✅ copy | Inalterado. |
| `crewai_crew/__init__.py` | ✅ copy | Inalterado. |
| `crewai_crew/agents.py` | ✅ copy | 3 agentes genéricos suficientes — especialização via tasks. |
| `image_gen/__init__.py` | ✅ copy | Inalterado. |
| `image_gen/lambda_handler.py` | ✅ copy | Parâmetros clínicos já presentes (white coat, hospital setting, no patient face). Inalterado. |
| `publish/__init__.py` | ✅ copy | Inalterado. |
| `publish/lambda_handler.py` | ✅ copy | Publicação Graph API independente de nicho. Inalterado. |
| `requirements.txt` | ✅ copy | Dependências não mudam. |
| `statemachine/definition.json` | ✅ patch | Estrutura de estados mantida. Estado EthicsGuardrail + CheckEthicsResult injetados automaticamente. RunCrewAI.Next atualizado para EthicsGuardrail. |

## Próximos passos manuais

1. Configurar SSM com BrandIdentity:
   ```bash
   aws ssm put-parameter \
     --name "/pulsocast/brand/musicoterapia-hospitalar/identity" \
     --type String \
     --value "$(cat ssm_brand_identity.json)"
   ```
2. Criar secret OpenAI em `/pulsocast/openai-api-key`
3. Criar secret IG token em `/pulsocast/ig-access-token`
4. Criar Lambda `EthicsGuardrailFunction` apontando para `guardrails_musicoterapia.py`
5. Atualizar ARNs no `statemachine/definition.json`
6. Executar `pip install -r requirements.txt`