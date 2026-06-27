"""Pydantic schemas: API request/response + Claude structured output."""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ---------- Job ----------
class JobCreate(BaseModel):
    title: str
    description: str
    required_skills: List[str] = []
    nice_to_have_skills: List[str] = []
    min_experience_years: float = 0.0
    keywords: List[str] = []
    location: str = "India"                 # for market-rate anchoring
    currency: str = "INR"
    budget_min: Optional[float] = None      # optional internal band (monthly)
    budget_max: Optional[float] = None


class JobOut(JobCreate):
    id: int
    class Config:
        from_attributes = True


# ---------- Claude structured output schemas ----------
class ContactInfo(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: List[str] = []


class WorkHistoryItem(BaseModel):
    company: str = ""
    title: str = ""
    start: str = ""
    end: str = ""
    summary: str = ""


class EducationItem(BaseModel):
    institution: str = ""
    degree: str = ""
    year: str = ""


class ParsedResume(BaseModel):
    contact: ContactInfo = ContactInfo()
    total_experience_years: float = 0.0
    education: List[EducationItem] = []
    work_history: List[WorkHistoryItem] = []
    technical_skills: List[str] = []
    soft_skills: List[str] = []


class SalaryEstimate(BaseModel):
    currency: str = "INR"
    period: str = "month"                      # month | year
    market_low: float = 0.0
    market_median: float = 0.0
    market_high: float = 0.0
    recommended_offer: float = 0.0            # what to open with
    within_budget: Optional[bool] = None      # null if no budget given
    negotiation_strategy: str = ""            # one concrete line
    basis: str = ""                           # what the estimate is anchored on


class Scorecard(BaseModel):
    """Strict schema Claude must return."""
    parsed: ParsedResume
    match_score: float = Field(ge=0, le=100)
    skill_alignment: float = Field(ge=0, le=100)
    experience_depth: float = Field(ge=0, le=100)
    relevancy: float = Field(ge=0, le=100)
    fit_analysis: str
    missing_critical_skills: List[str] = []
    red_flags: List[str] = []
    interview_questions: List[str] = []
    salary: SalaryEstimate = SalaryEstimate()
    recommendation: Literal["strong", "maybe", "reject"]


# ---------- API response ----------
class EvaluationOut(BaseModel):
    match_score: float
    skill_alignment: float
    experience_depth: float
    relevancy: float
    fit_analysis: str
    missing_critical_skills: List[str]
    red_flags: List[str]
    interview_questions: List[str]
    salary: dict = {}
    recommendation: str
    class Config:
        from_attributes = True


class CandidateOut(BaseModel):
    id: int
    job_id: int
    file_name: str
    full_name: str
    email: str
    phone: str
    status: str
    source: str = "upload"
    error_message: str
    evaluation: Optional[EvaluationOut] = None
    class Config:
        from_attributes = True
