FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py .
COPY guardrails_musicoterapia.py .
COPY agno_agent/ ./agno_agent/
COPY bridge/ ./bridge/
COPY crewai_crew/ ./crewai_crew/
COPY fallback/ ./fallback/
COPY image_gen/ ./image_gen/
COPY publish/ ./publish/

CMD ["agno_agent.trend_agent.lambda_handler"]
