"""Claude integration: parse + score a resume against a JD into a strict Scorecard.

Design notes:
- We force JSON-only output via a strict system prompt + a prefilled assistant turn
  beginning with '{' so Claude continues valid JSON (no markdown fences).
- We validate against the Pydantic `Scorecard` schema and retry on failure.
- The system prompt is engineered to be objective and bias-free: it instructs the
  model to ignore name, gender, age, nationality, photos, and other protected/
  irrelevant attributes, and to score only on job-relevant evidence.
"""
import json
import os
import time
from typing import Optional

from anthropic import Anthropic, APIError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from schemas import Scorecard

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 2000
MAX_RETRIES = 3

_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _client = Anthropic(api_key=key, timeout=60.0)
    return _client


SYSTEM_PROMPT = """You are an objective, bias-free resume screening engine for an HR team.

Your job: extract structured data from ONE resume and score it against ONE job description.

STRICT FAIRNESS RULES (non-negotiable):
- Score ONLY on job-relevant evidence: skills, experience, measurable outcomes, education relevance.
- IGNORE and NEVER let these influence the score: name, gender, age, ethnicity, nationality,
  religion, marital status, photos, gaps explained by caregiving/health, university prestige
  beyond relevance, and writing flourish. Judge substance, not polish.
- Do not infer protected attributes. If the resume is ambiguous, say so in fit_analysis rather
  than guessing.
- "red_flags" must be strictly job-relevant and evidence-based (e.g., unexplained multi-year gap,
  rapid unexplained job-hopping <6 months repeatedly, claimed skill contradicted elsewhere).
  Never list protected-attribute-based or speculative flags.

SCORING RUBRIC (0-100 each):
- skill_alignment: overlap with required + nice-to-have skills, weighted toward required.
- experience_depth: years and seniority relative to the job's minimum, plus evidence of impact.
- relevancy: how closely past roles/domain match the target role.
- match_score: holistic 0-100, roughly skill_alignment*0.45 + experience_depth*0.30 + relevancy*0.25,
  adjusted for critical missing skills.
- recommendation: "strong" (>=75 and no critical gaps), "maybe" (50-74 or fixable gaps), "reject" (<50 or missing must-haves).

SALARY ESTIMATION:
- Estimate a market compensation band for THIS candidate in the job's location and currency,
  anchored on their actual experience, seniority, and skill rarity — not a generic role average.
- "market_low/median/high": realistic monthly compensation for this seniority in that market.
- If an internal budget band is provided, set "within_budget" (true/false) and make
  "recommended_offer" land inside the budget when defensible; if the candidate's market value
  clearly exceeds budget, say so in "negotiation_strategy". If no budget is given, set
  "within_budget" to null and base "recommended_offer" on market median adjusted for fit.
- "negotiation_strategy": ONE concrete, actionable line (e.g. anchor point, what leverage you hold,
  what to offer beyond cash if budget is tight).
- "basis": one short phrase naming what the estimate is anchored on (e.g. "8 yrs backend, Tier-1 fintech, Bangalore").
- Be honest and conservative; do not inflate. If you are uncertain, widen the band and say so in basis.

OUTPUT RULES:
- Respond with a SINGLE JSON object ONLY. No prose, no markdown, no code fences.
- It MUST conform exactly to this schema (all keys required):
{
  "parsed": {
    "contact": {"full_name": str, "email": str, "phone": str, "location": str, "links": [str]},
    "total_experience_years": number,
    "education": [{"institution": str, "degree": str, "year": str}],
    "work_history": [{"company": str, "title": str, "start": str, "end": str, "summary": str}],
    "technical_skills": [str],
    "soft_skills": [str]
  },
  "match_score": number, "skill_alignment": number, "experience_depth": number, "relevancy": number,
  "fit_analysis": str,
  "missing_critical_skills": [str],
  "red_flags": [str],
  "interview_questions": [str],
  "salary": {
    "currency": str, "period": "month",
    "market_low": number, "market_median": number, "market_high": number,
    "recommended_offer": number, "within_budget": true|false|null,
    "negotiation_strategy": str, "basis": str
  },
  "recommendation": "strong" | "maybe" | "reject"
}
- interview_questions: 3-5 targeted questions probing the biggest uncertainties or gaps.
- Use empty string/array if a field is genuinely absent. Never invent contact details."""


# One compact few-shot example anchors format + objectivity.
FEWSHOT_USER = """JOB DESCRIPTION
Title: Backend Engineer
Location: Bangalore, India | Currency: INR
Internal budget (monthly): 150000 - 220000
Required skills: Python, PostgreSQL, REST APIs
Nice to have: AWS, Docker
Minimum experience (years): 3
Keywords: microservices, scalability

RESUME TEXT
Jordan Lee
jordan@example.com | +1-555-0100
Senior Software Engineer, FinCorp (2019-2024): Built Python microservices on PostgreSQL,
designed REST APIs serving 2M requests/day, deployed on AWS ECS with Docker.
B.S. Computer Science, 2018.
Skills: Python, PostgreSQL, REST, AWS, Docker, Kafka."""

FEWSHOT_ASSISTANT = """{"parsed":{"contact":{"full_name":"Jordan Lee","email":"jordan@example.com","phone":"+1-555-0100","location":"","links":[]},"total_experience_years":5.0,"education":[{"institution":"","degree":"B.S. Computer Science","year":"2018"}],"work_history":[{"company":"FinCorp","title":"Senior Software Engineer","start":"2019","end":"2024","summary":"Python microservices on PostgreSQL; REST APIs at 2M req/day; AWS ECS + Docker."}],"technical_skills":["Python","PostgreSQL","REST","AWS","Docker","Kafka"],"soft_skills":[]},"match_score":92,"skill_alignment":98,"experience_depth":88,"relevancy":90,"fit_analysis":"Meets all required skills with strong evidence of scale (2M req/day) and exceeds the 3-year minimum. Covers both nice-to-haves (AWS, Docker). Domain (fintech backend) is directly relevant.","missing_critical_skills":[],"red_flags":[],"interview_questions":["Walk through how you partitioned PostgreSQL for the 2M req/day workload.","How did you handle service-to-service failures across your microservices?","What drove the Kafka adoption and what trade-offs did you weigh?"],"salary":{"currency":"INR","period":"month","market_low":160000,"market_median":200000,"market_high":260000,"recommended_offer":210000,"within_budget":false,"negotiation_strategy":"Strong candidate above the top of budget; anchor at 210000 and close the gap with ESOPs or a 6-month review-linked raise rather than overshooting fixed pay.","basis":"5 yrs backend at scale, fintech, in-demand Kafka/AWS skills"},"recommendation":"strong"}"""


def _build_user_prompt(job, resume_text: str) -> str:
    if job.budget_min is not None and job.budget_max is not None:
        budget = f"{job.budget_min:.0f} - {job.budget_max:.0f}"
    else:
        budget = "not provided (estimate from market rate)"
    return f"""JOB DESCRIPTION
Title: {job.title}
Location: {job.location} | Currency: {job.currency}
Internal budget (monthly): {budget}
Description: {job.description}
Required skills: {", ".join(job.required_skills or [])}
Nice to have: {", ".join(job.nice_to_have_skills or [])}
Minimum experience (years): {job.min_experience_years}
Keywords: {", ".join(job.keywords or [])}

RESUME TEXT
{resume_text[:18000]}"""  # hard cap to bound token cost


def evaluate_resume(job, resume_text: str) -> Scorecard:
    """Call Claude and return a validated Scorecard. Raises on persistent failure."""
    client = _get_client()
    user_prompt = _build_user_prompt(job, resume_text)
    last_err: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": FEWSHOT_USER},
                    {"role": "assistant", "content": FEWSHOT_ASSISTANT},
                    {"role": "user", "content": user_prompt},
                    # Prefill forces JSON continuation (no fences/preamble):
                    {"role": "assistant", "content": "{"},
                ],
            )
            raw = "{" + resp.content[0].text
            data = json.loads(raw)
            return Scorecard.model_validate(data)

        except (APITimeoutError, RateLimitError, APIError) as e:
            last_err = e
            time.sleep(min(2 ** attempt, 10))  # exponential backoff
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            # On parse/schema failure, retry with a corrective nudge.
            user_prompt += "\n\nIMPORTANT: Return ONLY valid JSON matching the schema exactly."
            time.sleep(1)

    raise RuntimeError(f"Claude evaluation failed after {MAX_RETRIES} attempts: {last_err}")
