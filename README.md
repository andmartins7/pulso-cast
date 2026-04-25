# PulsoCast

**Detecta sinais. Gera estratégia. Publica conteúdo ético de Musicoterapia Hospitalar.**

PulsoCast é uma especialização do pipeline TrendCast para Musicoterapeuta Hospitalar. Combina análise de tendências em tempo real — cruzando redes sociais com publicações científicas — com geração multiagente de conteúdo para Instagram, respeitando integralmente o Código de Ética da UBAM (2018), as Diretrizes Éticas da ABMT (2025) e a Lei Federal 14.842/2024.

---

## Como funciona

```
Fontes científicas          Redes sociais
(PubMed · SciELO ·          (Instagram · YouTube ·
 Rev. Bras. MT · WFMT)       TikTok · Twitter/X)
        │                          │
        └──────────┬───────────────┘
                   ▼
   [Agno — MT Trend Agent]
   Camada 0: captura de sinais (ciência + social)
   Camada 1: processamento → ContentStrategyRecommendation
             (pilar · setor · ângulo · gancho · âncoras científicas · riscos éticos)
        │  TrendPayload + ContentStrategy
        ▼
   [Lambda Bridge v2]
   Valida · sanitiza · mescla BrandIdentity (SSM) + ContentStrategy (Agno)
        │  ContextBrief
        ▼
   [CrewAI — Post Generator]
   Analista Clínico → Copywriter de Saúde → Diretor Visual Hospitalar
        │  PostOutput
        ▼
   [Guardrails Éticos]
   Validação automática: linguagem de cura · identificação de paciente ·
   necessidade de TCLE · ausência de identificação profissional
        │
        ▼
   [Revisão humana]  (SQS waitForTaskToken — opcional)
        │
        ▼
   [Image Gen]
   DALL-E 3 → jaleco · ambiente hospitalar · sem rosto de paciente
   Fallback: Titan Image Generator v2 (Bedrock)
        │
        ▼
   [Instagram Graph API]
   Publica post + primeiro comentário com hashtags
        │
        ▼
   [DynamoDB]
   Registro de publicação · métricas de engajamento · rastreabilidade ética
```

Orquestração: **AWS Step Functions Express**

---

## Separação de responsabilidades (mudança arquitetural central)

A distinção entre o que é estático e o que é dinâmico é o núcleo do PulsoCast:

| O que muda raramente | O que muda a cada execução |
|---|---|
| `BrandIdentity` (SSM) | `ContentStrategyRecommendation` (Agno) |
| Voz e valores da marca | Pilar do dia |
| Identificação profissional | Setor hospitalar relevante |
| Linguagem proibida (ética) | Ângulo narrativo |
| Disclaimers obrigatórios | Ganchos para o caption |
| Contexto clínico geral | Âncoras científicas emergentes |
| — | Riscos éticos contextuais |
| — | `requires_tcle` / `show_epi` |

O Agno não entrega apenas sinais brutos — entrega **estratégia**. A Lambda Bridge não decide o que publicar — apenas valida, sanitiza e formata.

---

## Os 5 pilares de conteúdo

Gerados dinamicamente pelo Agno com base nos sinais capturados:

| Pilar | Quando o Agno escolhe | Exemplos |
|---|---|---|
| **Ciência** | Novo estudo relevante em MT clínica | Cortisol, NMT, revisão sistemática |
| **Humanização** | Engajamento alto em relatos de vínculo | Paliativo, UTI, família presente |
| **Bastidores** | Tendência de "day in the life" em saúde | Mala para UTI, higienização, EPI |
| **Educação** | Mito circulando sobre MT nas redes | Mito x Verdade, desmistificação |
| **Setor Hospitalar** | Evento ou data clínica específica | UTI, Oncologia Ped., Neonatal |

---

## Setores hospitalares cobertos

UTI · Oncologia Pediátrica · Cuidados Paliativos · UTI Neonatal · Reabilitação Neurológica · Saúde Mental/Psiquiatria · Maternidade · Geral

---

## Stack

| Camada | Tecnologia |
|---|---|
| Análise de tendências | Agno + ExaTools (PubMed · SciELO · RBMT · redes sociais) + GoogleSearchTools |
| Modelos LLM | Claude Sonnet 4 via Amazon Bedrock |
| Geração de conteúdo | CrewAI — 3 agentes especializados em saúde |
| Geração de imagem | DALL-E 3 (primário) · Titan Image Generator v2 (fallback) |
| Orquestração | AWS Step Functions Express |
| Execução | AWS Lambda (Python 3.12) |
| Armazenamento vetorial | ChromaDB |
| Identidade de marca | AWS SSM Parameter Store (`BrandIdentity`) |
| Segredos | AWS Secrets Manager (token IG · chave OpenAI) |
| Persistência | DynamoDB |
| Assets | S3 + CloudFront |
| Guardrails éticos | Módulo `guardrails_musicoterapia.py` (UBAM + ABMT + LGPD) |
| Observabilidade | AgentOps · CloudWatch |
| Validação de schemas | Pydantic v2 |

---

## Estrutura

```
pulsocast/
├── schemas_v2.py                          # Contratos Pydantic v2
│                                          #   BrandIdentity · ContentStrategyRecommendation
│                                          #   TrendPayload · ContextBrief · PostOutput
├── agno_agent/
│   └── trend_agent_musicoterapia.py       # Agno MT agent — Camadas 0+1
│                                          # Output: TrendPayload + ContentStrategy
├── bridge/
│   └── lambda_bridge_v2.py               # Merge BrandIdentity + TrendPayload+Strategy → ContextBrief
├── crewai_crew/
│   ├── agents.py                          # 3 agentes especializados em saúde hospitalar
│   ├── tasks_musicoterapia_hospitalar.py  # Tasks com contexto clínico e guardrails no prompt
│   └── instagram_crew.py                 # Orquestrador do crew + Lambda handler
├── guardrails_musicoterapia.py           # Validação ética pós-geração (UBAM + ABMT + LGPD)
├── image_gen_lambda.py                   # DALL-E 3 (jaleco · ambiente clínico · sem rosto)
├── publish_lambda.py                     # Instagram Graph API + primeiro comentário
├── statemachine/
│   └── definition.json                   # Step Functions: 14 estados com gate ético
├── ssm_brand_identity.json               # Template SSM — BrandIdentity imutável
└── requirements.txt
```

---

## Guardrails éticos automáticos

Executados entre o `RunCrewAI` e o `GenerateImage`:

| Nível | Referência | Gatilho |
|---|---|---|
| 🚫 BLOCK | UBAM Art. 49 + ABMT Seção 5 | Linguagem de cura (`cura`, `curou`, `música cura`) |
| 🚫 BLOCK | UBAM Art. 16, 52 + LGPD | Padrões que identificam paciente |
| 🚫 BLOCK | UBAM Art. 49 + ABMT Seção 5 | Garantias de resultado |
| 🚫 BLOCK | UBAM Art. 49a + ABMT Seção 6 | Preço como propaganda |
| ⚠️ WARN | UBAM Art. 16, 43, 52 | Relato de caso sem TCLE verificado |
| ⚠️ WARN | ABMT Seção 2 | Mistura de profissões no mesmo post |
| ⚠️ WARN | ABMT Seção 3 | Título Dr./Me. sem verificação |
| ⚠️ WARN | UBAM Art. 20, 35 | Equiparação a lazer ou entretenimento |
| 💡 SUGGEST | UBAM Art. 48 + ABMT Seção 1 | Ausência de identificação profissional |
| 💡 SUGGEST | UBAM Art. 35 | Post técnico sem âncora científica |

Posts bloqueados retornam ao CrewAI com feedback estruturado para reescrita. Posts com avisos pausam para revisão humana via SQS.

---

## Configuração

### 1. Variáveis de ambiente (Lambda)

```bash
AWS_REGION=us-east-1
LOG_LEVEL=INFO
IMAGE_BUCKET=pulsocast-assets
S3_URL_TYPE=presigned
PRESIGNED_TTL_SECONDS=3600
OPENAI_SECRET_NAME=/pulsocast/openai-api-key
IG_TOKEN_SECRET=/pulsocast/ig-access-token
PUBLISH_TABLE=pulsocast-publish-log
```

### 2. SSM — BrandIdentity (apenas identidade imutável)

```bash
aws ssm put-parameter \
  --name "/pulsocast/brand/musicoterapia-hospitalar/identity" \
  --type String \
  --value "$(cat ssm_brand_identity.json)"
```

### 3. Secrets Manager

```bash
# OpenAI API key
aws secretsmanager create-secret \
  --name /pulsocast/openai-api-key \
  --secret-string '{"api_key": "sk-..."}'

# Instagram long-lived access token
aws secretsmanager create-secret \
  --name /pulsocast/ig-access-token \
  --secret-string '{"access_token": "EAABsbCS..."}'
```

### 4. Dependências

```bash
pip install -r requirements.txt
```

---

## Execução

### Via Step Functions

```json
{
  "niche":                "musicoterapia hospitalar",
  "language":             "pt-BR",
  "brand_id":             "musicoterapia-hospitalar",
  "post_format":          null,
  "n_slides":             5,
  "instagram_account_id": "SEU_IG_ACCOUNT_ID",
  "require_approval":     true
}
```

`post_format: null` instrui o pipeline a usar o formato recomendado pelo Agno com base nos sinais capturados. Passe um valor explícito (`"feed"`, `"reel"`, `"carousel"`) apenas para forçar um formato específico.

---

## Política de modelos

| Agente | Modelo | Temperatura | Finalidade |
|---|---|---|---|
| MT Trend Agent | Claude Sonnet 4 | padrão | Análise, scoring e ContentStrategy |
| Analista Clínico | Claude Sonnet 4 (Bedrock) | 0.4 | Briefing criativo clínico |
| Copywriter de Saúde | Claude Sonnet 4 (Bedrock) | 0.8 | Redação com guardrails éticos |
| Diretor Visual Hospitalar | Claude Sonnet 4 (Bedrock) | 0.6 | Brief visual clínico (jaleco, EPI, sem paciente) |
| Image Gen (primário) | DALL-E 3 | — | Imagem com parâmetros clínicos obrigatórios |
| Image Gen (fallback) | Titan Image Generator v2 | — | Fallback serverless via Bedrock |

---

## Frameworks éticos

- Código Nacional de Ética, Orientação e Disciplina do Musicoterapeuta — **UBAM (2018)**
- Diretrizes e Orientações Éticas para Musicoterapeutas — **ABMT (2025)**
- Lei Federal **14.842/2024** — Regulamentação da profissão de musicoterapeuta
- **LGPD** — Lei nº 13.709/2018
- Code of Ethics — **World Federation of Music Therapy (WFMT, 2022)**

---

## Roadmap

- [ ] Gate `EthicsGuardrail` na Step Functions (estado explícito entre `RunCrewAI` e `GenerateImage`)
- [ ] Lambda de métricas de engajamento pós-publicação com retorno ao Vector Store do Agno
- [ ] Suporte a múltiplos perfis de musicoterapeutas (multi-tenant por `brand_id`)
- [ ] Agente de validação de brand alignment (score automático pré-revisão)
- [ ] GraphRAG: modelar relações pilar → setor → formato → performance histórica

---

## Licença

MIT — consulte `LICENSE` para os termos completos.
