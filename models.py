"""ORM models: Job, Candidate, Evaluation."""
import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from database import Base


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    required_skills = Column(JSON, default=list)        # ["Python", "SQL"]
    nice_to_have_skills = Column(JSON, default=list)
    min_experience_years = Column(Float, default=0.0)
    keywords = Column(JSON, default=list)
    location = Column(String(255), default="India")
    currency = Column(String(8), default="INR")
    budget_min = Column(Float, nullable=True)
    budget_max = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_now)

    candidates = relationship("Candidate", back_populates="job",
                              cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    file_name = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)
    raw_text = Column(Text, default="")
    # parsed structured fields (denormalized for quick listing)
    full_name = Column(String(255), default="")
    email = Column(String(255), default="")
    phone = Column(String(64), default="")
    parsed_data = Column(JSON, default=dict)            # full structured parse
    status = Column(String(32), default="pending")      # pending|processing|done|error
    source = Column(String(32), default="upload")       # upload|meta_ads|portal|email
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=_now)

    job = relationship("Job", back_populates="candidates")
    evaluation = relationship("Evaluation", back_populates="candidate",
                              uselist=False, cascade="all, delete-orphan")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"),
                          nullable=False, unique=True, index=True)
    match_score = Column(Float, default=0.0)            # 0-100
    skill_alignment = Column(Float, default=0.0)
    experience_depth = Column(Float, default=0.0)
    relevancy = Column(Float, default=0.0)
    fit_analysis = Column(Text, default="")
    missing_critical_skills = Column(JSON, default=list)
    red_flags = Column(JSON, default=list)
    interview_questions = Column(JSON, default=list)
    salary = Column(JSON, default=dict)                 # SalaryEstimate dump
    recommendation = Column(String(32), default="")     # strong|maybe|reject
    created_at = Column(DateTime, default=_now)

    candidate = relationship("Candidate", back_populates="evaluation")
