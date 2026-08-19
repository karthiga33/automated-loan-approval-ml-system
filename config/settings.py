"""
Loan Approval System - Configuration Settings
All environment-specific settings managed here.
"""
import os

# AWS Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "loan-approval-ml-system")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "LoanApprovalDecisions")
DYNAMODB_DOCUMENTS_TABLE = os.environ.get("DYNAMODB_DOCUMENTS_TABLE", "LoanApprovalDocuments")

# Model Configuration
MODEL_KEY = "models/loan_approval_pipeline.pkl"
PREPROCESSING_KEY = "models/loan_preprocessing_pipeline.pkl"

# Application Settings
APPLICATION_PREFIX = "applications"
RAW_PREFIX = "raw"
PROCESSED_PREFIX = "processed"
PREDICTIONS_PREFIX = "predictions"
DOCUMENTS_PREFIX = "documents"

# CIBIL Configuration (Mock for now - plug real API later)
CIBIL_API_URL = os.environ.get("CIBIL_API_URL", "mock")
CIBIL_API_KEY = os.environ.get("CIBIL_API_KEY", "")
CIBIL_MODE = os.environ.get("CIBIL_MODE", "mock")  # "mock" or "live"

# Credit Score Thresholds (Indian CIBIL scale: 300-900)
CIBIL_MIN_SCORE = 300
CIBIL_MAX_SCORE = 900
CIBIL_GOOD_SCORE = 750
CIBIL_FAIR_SCORE = 650
CIBIL_POOR_SCORE = 550

# Loan Decision Thresholds
ML_CONFIDENCE_AUTO_APPROVE = 0.85  # Above this = auto approve
ML_CONFIDENCE_AUTO_REJECT = 0.80   # Above this = auto reject
ML_CONFIDENCE_MANUAL_REVIEW = 0.50  # Below auto thresholds = human review

# Document Verification
SUPPORTED_DOCUMENT_TYPES = [
    "aadhaar",
    "pan",
    "salary_slip",
    "bank_statement",
    "photograph"
]
MAX_DOCUMENT_SIZE_MB = 10
ALLOWED_FILE_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png"]

# API Settings
API_PORT = int(os.environ.get("API_PORT", "8000"))
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-this-in-production")
JWT_EXPIRY_HOURS = 24
RATE_LIMIT_PER_MINUTE = 60

# Feature Columns (for ML model)
FEATURE_COLUMNS = [
    "person_age",
    "person_income",
    "person_emp_exp",
    "loan_amnt",
    "loan_int_rate",
    "loan_percent_income",
    "cb_person_cred_hist_length",
    "person_gender",
    "employment_type",
    "person_home_ownership",
    "loan_intent",
    "account_type",
    "person_education",
    "previous_loan_defaults_on_file"
]

# Enhanced Features (added from document verification + CIBIL)
ENHANCED_FEATURE_COLUMNS = FEATURE_COLUMNS + [
    "cibil_score",
    "active_loans_count",
    "total_outstanding_debt",
    "monthly_obligations",
    "verified_income",
    "income_match_score",
    "document_verification_score"
]
