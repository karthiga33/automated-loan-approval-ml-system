"""
Loan Approval System - LOCAL VERSION
Run this on your machine. No AWS required.
All data stored locally in /local_data folder.

Usage:
    pip install flask pandas scikit-learn joblib numpy
    python app_local.py

Then open: http://localhost:8000
"""
import os
import sys
import json
import uuid
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path

# Add parent path for services
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.cibil_service import CIBILService
from services.explainability import LoanExplainabilityService
from services.input_validator import LoanApplicationValidator
from services.loan_tracker import LoanTracker

# ============================================================
# APP SETUP
# ============================================================
app = Flask(__name__, static_folder="frontend", static_url_path="/static")

# Local data directory (instead of S3/DynamoDB)
LOCAL_DATA_DIR = Path("local_data")
LOCAL_DATA_DIR.mkdir(exist_ok=True)
(LOCAL_DATA_DIR / "applications").mkdir(exist_ok=True)
(LOCAL_DATA_DIR / "decisions").mkdir(exist_ok=True)
(LOCAL_DATA_DIR / "documents").mkdir(exist_ok=True)
(LOCAL_DATA_DIR / "models").mkdir(exist_ok=True)

# Services
cibil_service = CIBILService(mode="mock")
explainability_service = LoanExplainabilityService()
validator = LoanApplicationValidator()
loan_tracker = LoanTracker(data_dir="local_data")

# ML Model
MODEL_CACHE = {}


def train_local_model():
    """Train model locally from CSV data if no model exists."""
    model_path = LOCAL_DATA_DIR / "models" / "loan_approval_pipeline.pkl"

    if model_path.exists():
        print("  Model already exists, loading...")
        return joblib.load(model_path)

    data_path = Path("data/loan-data.csv")
    if not data_path.exists():
        print("  WARNING: No training data found at data/loan-data.csv")
        print("  Using rule-based fallback for predictions")
        return None

    print("  Training ML model from loan-data.csv...")
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, OrdinalEncoder
    from sklearn.compose import ColumnTransformer

    df = pd.read_csv(data_path)
    print(f"  Loaded {len(df)} records")

    numeric_features = ['person_age', 'person_income', 'person_emp_exp', 'loan_amnt',
                       'loan_int_rate', 'loan_percent_income', 'cb_person_cred_hist_length']
    categorical_features = ['person_gender', 'employment_type', 'person_home_ownership',
                           'loan_intent', 'account_type', 'person_education',
                           'previous_loan_defaults_on_file']

    target = 'loan_status'
    all_features = numeric_features + categorical_features

    # Filter available columns
    available_numeric = [f for f in numeric_features if f in df.columns]
    available_categorical = [f for f in categorical_features if f in df.columns]
    available_features = available_numeric + available_categorical

    if target not in df.columns:
        print(f"  ERROR: Target column '{target}' not found")
        return None

    X = df[available_features].copy()
    y = df[target].copy()

    # Handle missing values
    for col in available_numeric:
        X[col] = X[col].fillna(X[col].median())
    for col in available_categorical:
        X[col] = X[col].fillna('Unknown')

    # Pipeline
    preprocessor = ColumnTransformer(transformers=[
        ('num', StandardScaler(), available_numeric),
        ('cat', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1), available_categorical)
    ])

    pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('classifier', RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1))
    ])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    pipeline.fit(X_train, y_train)
    accuracy = pipeline.score(X_test, y_test)
    print(f"  Model trained! Accuracy: {accuracy:.4f}")

    joblib.dump(pipeline, model_path)
    print(f"  Model saved to {model_path}")
    return pipeline


def get_model():
    """Get or load the ML model."""
    if "pipeline" not in MODEL_CACHE:
        MODEL_CACHE["pipeline"] = train_local_model()
    return MODEL_CACHE["pipeline"]


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    """Serve the customer portal."""
    return send_from_directory("frontend", "index.html")


@app.route("/emi")
def emi_page():
    """EMI Calculator page."""
    return send_from_directory("frontend", "emi-calculator.html")


@app.route("/eligibility")
def eligibility_page():
    """Eligibility check page."""
    return send_from_directory("frontend", "eligibility.html")


@app.route("/track")
def track_page():
    """Application tracking page."""
    return send_from_directory("frontend", "track.html")


@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return jsonify({
        "status": "healthy",
        "service": "Loan Approval System (Local)",
        "model_loaded": MODEL_CACHE.get("pipeline") is not None,
        "timestamp": datetime.now().isoformat(),
        "mode": "local"
    })


@app.route("/api/applications/submit", methods=["POST"])
def submit_application():
    """Submit a loan application and get instant decision."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Application data required"}), 400

    # Step 1: Validate
    is_valid, errors, sanitized_data = validator.validate_application(data)
    if not is_valid:
        return jsonify({
            "status": "validation_failed",
            "errors": [e.to_dict() for e in errors]
        }), 400

    # Step 2: Generate application ID
    application_id = f"LA-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    sanitized_data["application_id"] = application_id
    sanitized_data["submission_timestamp"] = datetime.now().isoformat()

    # Step 3: Save locally
    app_file = LOCAL_DATA_DIR / "applications" / f"{application_id}.json"
    with open(app_file, "w") as f:
        json.dump(sanitized_data, f, indent=2)

    # Step 4: CIBIL check (mock)
    cibil_report = None
    if sanitized_data.get("consent_cibil_check"):
        cibil_report = cibil_service.get_credit_report(
            pan_number=sanitized_data["pan_number"], consent=True
        )

    # Step 5: ML Prediction
    prediction_result = make_prediction(sanitized_data, cibil_report)

    # Step 6: Explanation
    explanation = explainability_service.generate_explanation(
        application_data=sanitized_data,
        decision=prediction_result["decision"],
        confidence=prediction_result["confidence"],
        cibil_report=cibil_report,
        verification_result=None
    )

    # Step 7: Build response
    response = {
        "status": "processed",
        "application_id": application_id,
        "decision": prediction_result["decision"],
        "confidence": round(prediction_result["confidence"] * 100, 1),
        "explanation": explanation,
        "cibil_score": (
            cibil_report.get("credit_score", {}).get("score")
            if cibil_report and cibil_report.get("status") == "success"
            else None
        ),
        "next_steps": get_next_steps(prediction_result["decision"]),
        "timestamp": datetime.now().isoformat()
    }

    # Step 8: Save decision locally
    decision_file = LOCAL_DATA_DIR / "decisions" / f"{application_id}.json"
    with open(decision_file, "w") as f:
        json.dump(response, f, indent=2)

    return jsonify(response), 200


@app.route("/api/applications/<application_id>/verify-documents", methods=["POST"])
def verify_documents(application_id):
    """Instantly verify uploaded documents against application data."""
    import re

    # Load application data
    app_file = LOCAL_DATA_DIR / "applications" / f"{application_id}.json"
    if not app_file.exists():
        return jsonify({"error": "Application not found"}), 404

    with open(app_file) as f:
        app_data = json.load(f)

    # Load uploaded documents
    doc_dir = LOCAL_DATA_DIR / "documents" / application_id
    if not doc_dir.exists() or not list(doc_dir.iterdir()):
        return jsonify({"error": "No documents uploaded yet"}), 400

    # Read all uploaded document files (support PDF and plain text)
    extracted = {}
    for doc_file in doc_dir.iterdir():
        try:
            suffix = doc_file.suffix.lower()
            if suffix == ".pdf":
                # Extract text from PDF using PyPDF2
                try:
                    import PyPDF2
                    content = ""
                    with open(doc_file, "rb") as pdf_f:
                        reader = PyPDF2.PdfReader(pdf_f)
                        for page in reader.pages:
                            page_text = page.extract_text()
                            if page_text:
                                content += page_text + "\n"
                except Exception as pdf_err:
                    print(f"PDF read error for {doc_file.name}: {pdf_err}")
                    content = ""
            else:
                # Plain text / other formats
                content = doc_file.read_text(encoding="utf-8", errors="ignore")
            extracted[doc_file.name] = content
        except Exception:
            continue

    # Cross-verification checks
    checks = []
    all_text = "\n".join(extracted.values())

    # CHECK 1: Name verification
    form_name = app_data.get("full_name", "").upper()
    name_found = form_name.split()[0].upper() in all_text.upper() if form_name else False
    checks.append({
        "check": "Name Verification",
        "field": "Full Name",
        "form_value": app_data.get("full_name", ""),
        "status": "PASSED" if name_found else "FAILED",
        "detail": "Name found in uploaded documents" if name_found else "Name not found in documents"
    })

    # CHECK 2: PAN number verification
    form_pan = app_data.get("pan_number", "").upper()
    pan_found = form_pan in all_text.upper() if form_pan else False
    checks.append({
        "check": "PAN Verification",
        "field": "PAN Number",
        "form_value": form_pan,
        "status": "PASSED" if pan_found else "FAILED",
        "detail": "PAN number matches in documents" if pan_found else "PAN number not found in documents"
    })

    # CHECK 3: Aadhaar number verification
    form_aadhaar = app_data.get("aadhaar_number", "").replace(" ", "")
    aadhaar_found = False
    # Search with spaces too
    for fmt in [form_aadhaar, f"{form_aadhaar[:4]} {form_aadhaar[4:8]} {form_aadhaar[8:]}"]:
        if fmt in all_text:
            aadhaar_found = True
            break
    checks.append({
        "check": "Aadhaar Verification",
        "field": "Aadhaar Number",
        "form_value": form_aadhaar,
        "status": "PASSED" if aadhaar_found else "FAILED",
        "detail": "Aadhaar number matches" if aadhaar_found else "Aadhaar number not found in documents"
    })

    # CHECK 4: Income verification (from salary slips)
    form_income = app_data.get("person_income", 0)
    monthly_form = form_income / 12 if form_income > 0 else 0
    # Match "NET SALARY (Take Home)" style labels — number may follow on same or next line
    salary_amounts = re.findall(
        r"(?:NET SALARY|Net Salary|Take Home|NET PAY|Net Pay)[^\d\n]{0,30}([\d,]+)",
        all_text,
        re.IGNORECASE
    )
    salary_found = None
    if salary_amounts:
        salary_found = float(salary_amounts[0].replace(",", ""))

    income_match = False
    income_detail = "No salary data found in documents"
    if salary_found and monthly_form:
        ratio = min(salary_found, monthly_form) / max(salary_found, monthly_form)
        income_match = ratio > 0.7
        income_detail = f"Form: ₹{monthly_form:,.0f}/month, Document: ₹{salary_found:,.0f}/month (Match: {ratio:.0%})"

    checks.append({
        "check": "Income Verification",
        "field": "Monthly Income",
        "form_value": f"₹{monthly_form:,.0f}/month",
        "status": "PASSED" if income_match else "WARNING",
        "detail": income_detail
    })

    # CHECK 5: Employer verification
    gross_amounts = re.findall(r"(?:GROSS SALARY|Gross Salary)[^\d]*?([\d,]+)", all_text)
    employer_names = re.findall(r"(?:INFOSYS|TCS|WIPRO|HCL|COGNIZANT|ACCENTURE|IBM|GOOGLE|MICROSOFT|AMAZON)", all_text, re.IGNORECASE)
    employer_found = len(employer_names) > 0
    checks.append({
        "check": "Employer Verification",
        "field": "Employer",
        "form_value": "From salary slip / appointment letter",
        "status": "PASSED" if employer_found else "WARNING",
        "detail": f"Employer found: {employer_names[0].title()}" if employer_found else "Employer name not clearly identified"
    })

    # CHECK 6: Bank account verification
    bank_names = re.findall(r"(?:STATE BANK|SBI|HDFC|ICICI|AXIS|KOTAK|PNB)", all_text, re.IGNORECASE)
    account_numbers = re.findall(r"\b\d{10,14}\b", all_text)
    bank_found = len(bank_names) > 0
    checks.append({
        "check": "Bank Account Verification",
        "field": "Bank Details",
        "form_value": "From bank statement",
        "status": "PASSED" if bank_found else "WARNING",
        "detail": f"Bank identified: {bank_names[0].upper()}" if bank_found else "Bank details not clearly identified"
    })

    # CHECK 7: Address verification
    pin_codes = re.findall(r"\b[1-9]\d{5}\b", all_text)
    address_found = len(pin_codes) > 0
    checks.append({
        "check": "Address Verification",
        "field": "Address/PIN Code",
        "form_value": "From Aadhaar/Address Proof",
        "status": "PASSED" if address_found else "WARNING",
        "detail": f"PIN Code found: {pin_codes[0]}" if address_found else "Address/PIN not found"
    })

    # Calculate overall score
    passed = sum(1 for c in checks if c["status"] == "PASSED")
    total = len(checks)
    score = round(passed / total * 100)

    if score >= 80:
        overall_status = "VERIFIED"
        overall_message = "All documents verified successfully. Your application is approved for processing."
    elif score >= 50:
        overall_status = "PARTIALLY_VERIFIED"
        overall_message = "Some documents need attention. Please ensure uploaded documents are clear and match your application."
    else:
        overall_status = "VERIFICATION_FAILED"
        overall_message = "Document verification failed. Please re-upload clear copies of your documents."

    return jsonify({
        "application_id": application_id,
        "verification_status": overall_status,
        "verification_score": score,
        "message": overall_message,
        "checks_passed": passed,
        "checks_total": total,
        "checks": checks,
        "documents_uploaded": len(extracted),
        "timestamp": datetime.now().isoformat()
    })


@app.route("/api/emi/calculate", methods=["POST"])
def calculate_emi():
    """Calculate EMI and generate repayment schedule."""
    data = request.get_json()
    loan_amount = float(data.get("loan_amount", 0))
    interest_rate = float(data.get("interest_rate", 8.5))
    tenure_months = int(data.get("tenure_months", 36))

    if loan_amount <= 0 or tenure_months <= 0:
        return jsonify({"error": "Invalid loan amount or tenure"}), 400

    # EMI Formula: EMI = P × r × (1+r)^n / ((1+r)^n - 1)
    monthly_rate = interest_rate / 12 / 100
    if monthly_rate == 0:
        emi = loan_amount / tenure_months
    else:
        emi = loan_amount * monthly_rate * ((1 + monthly_rate) ** tenure_months) / (((1 + monthly_rate) ** tenure_months) - 1)

    total_payment = emi * tenure_months
    total_interest = total_payment - loan_amount

    # Generate repayment schedule
    schedule = []
    balance = loan_amount
    for month in range(1, tenure_months + 1):
        interest_component = balance * monthly_rate
        principal_component = emi - interest_component
        balance -= principal_component
        if balance < 0:
            balance = 0

        schedule.append({
            "month": month,
            "emi": round(emi, 2),
            "principal": round(principal_component, 2),
            "interest": round(interest_component, 2),
            "balance": round(balance, 2)
        })

    return jsonify({
        "loan_amount": loan_amount,
        "interest_rate": interest_rate,
        "tenure_months": tenure_months,
        "monthly_emi": round(emi, 2),
        "total_payment": round(total_payment, 2),
        "total_interest": round(total_interest, 2),
        "schedule": schedule
    })


@app.route("/api/eligibility/check", methods=["POST"])
def check_eligibility():
    """Quick eligibility pre-check before full application."""
    data = request.get_json()
    income = float(data.get("monthly_income", 0))
    age = int(data.get("age", 30))
    cibil_score = int(data.get("cibil_score", 700))

    if income <= 0:
        return jsonify({"error": "Monthly income is required"}), 400

    # Existing-loan concept removed: EMI capacity is based purely on income.
    available_for_emi = income * 0.50
    if available_for_emi < 0:
        available_for_emi = 0

    # Max tenure based on age (retirement at 60)
    max_tenure_years = min(30, 60 - age)
    if max_tenure_years < 1:
        max_tenure_years = 1
    max_tenure_months = max_tenure_years * 12

    # Calculate max loan amount (at 8.5% interest)
    rate = 8.5 / 12 / 100
    if available_for_emi > 0 and rate > 0:
        max_loan = available_for_emi * (((1 + rate) ** max_tenure_months) - 1) / (rate * ((1 + rate) ** max_tenure_months))
    else:
        max_loan = 0

    # Adjust based on CIBIL score
    if cibil_score >= 750:
        multiplier = 1.0
        risk = "LOW"
    elif cibil_score >= 700:
        multiplier = 0.85
        risk = "MODERATE"
    elif cibil_score >= 650:
        multiplier = 0.65
        risk = "HIGH"
    else:
        multiplier = 0.3
        risk = "VERY HIGH"

    max_loan_adjusted = max_loan * multiplier

    # Interest rate based on score
    if cibil_score >= 750:
        offered_rate = 8.5
    elif cibil_score >= 700:
        offered_rate = 10.5
    elif cibil_score >= 650:
        offered_rate = 13.0
    else:
        offered_rate = 16.0

    return jsonify({
        "eligible": max_loan_adjusted > 50000,
        "max_loan_amount": round(max_loan_adjusted, 0),
        "max_emi_affordable": round(available_for_emi, 0),
        "suggested_interest_rate": offered_rate,
        "max_tenure_months": max_tenure_months,
        "risk_category": risk,
        "monthly_income": income,
        "tips": _get_eligibility_tips(max_loan_adjusted, cibil_score, income)
    })


def _get_eligibility_tips(max_loan, cibil, income):
    tips = []
    if cibil < 750:
        tips.append("Improving your CIBIL score above 750 can increase your eligible amount by 15-30%")
    if max_loan < 100000:
        tips.append("Consider adding a co-applicant to increase your loan eligibility")
    if max_loan > 0:
        tips.append(f"You may be eligible for up to ₹{max_loan:,.0f} based on your income")
    return tips


@app.route("/api/applications/track", methods=["POST"])
def track_application():
    """Track application status by Application ID."""
    data = request.get_json()
    app_id = data.get("application_id", "").strip()

    if not app_id:
        return jsonify({"error": "Application ID is required"}), 400

    # Check in decisions
    decision_file = LOCAL_DATA_DIR / "decisions" / f"{app_id}.json"
    app_file = LOCAL_DATA_DIR / "applications" / f"{app_id}.json"
    doc_dir = LOCAL_DATA_DIR / "documents" / app_id

    if not decision_file.exists() and not app_file.exists():
        return jsonify({"error": "Application not found. Please check your Application ID."}), 404

    # Build timeline
    timeline = []
    app_data = {}
    decision_data = {}

    if app_file.exists():
        with open(app_file) as f:
            app_data = json.load(f)
        timeline.append({
            "step": "Application Submitted",
            "status": "completed",
            "timestamp": app_data.get("submission_timestamp", ""),
            "detail": f"Loan application for ₹{app_data.get('loan_amnt', 0):,.0f} submitted"
        })

    if decision_file.exists():
        with open(decision_file) as f:
            decision_data = json.load(f)
        timeline.append({
            "step": "AI Decision",
            "status": "completed",
            "timestamp": decision_data.get("timestamp", ""),
            "detail": f"Decision: {decision_data.get('decision', 'N/A')} (Confidence: {decision_data.get('confidence', 0)}%)"
        })

    docs_uploaded = False
    if doc_dir and doc_dir.exists():
        doc_count = len(list(doc_dir.iterdir()))
        if doc_count > 0:
            docs_uploaded = True
            timeline.append({
                "step": "Documents Uploaded",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "detail": f"{doc_count} document(s) uploaded and verified"
            })

    # Remaining steps
    if docs_uploaded:
        timeline.append({"step": "e-KYC Verification", "status": "pending", "timestamp": "", "detail": "Video KYC call scheduled within 24 hours"})
        timeline.append({"step": "Loan Sanction", "status": "upcoming", "timestamp": "", "detail": "Sanction letter will be issued after e-KYC"})
        timeline.append({"step": "Agreement Signing", "status": "upcoming", "timestamp": "", "detail": "Digital e-Sign via Aadhaar OTP"})
        timeline.append({"step": "Disbursement", "status": "upcoming", "timestamp": "", "detail": "Amount transferred to your bank account"})
    else:
        timeline.append({"step": "Document Upload", "status": "pending", "timestamp": "", "detail": "Please upload required documents"})

    return jsonify({
        "application_id": app_id,
        "applicant_name": app_data.get("full_name", "N/A"),
        "loan_amount": app_data.get("loan_amnt", 0),
        "loan_purpose": app_data.get("loan_intent", "N/A"),
        "decision": decision_data.get("decision", "PENDING"),
        "confidence": decision_data.get("confidence", 0),
        "current_stage": timeline[-1]["step"] if timeline else "Unknown",
        "timeline": timeline
    })


@app.route("/api/applications/<application_id>/status", methods=["GET"])
def get_status(application_id):
    """Check application status."""
    decision_file = LOCAL_DATA_DIR / "decisions" / f"{application_id}.json"
    if decision_file.exists():
        with open(decision_file) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Application not found"}), 404


@app.route("/tracker")
def tracker_page():
    """Serve the loan tracking page."""
    return send_from_directory("frontend", "tracker.html")


@app.route("/admin")
def admin_page():
    """Serve the admin dashboard."""
    return send_from_directory("frontend", "admin.html")


@app.route("/api/loans/create", methods=["POST"])
def create_loan():
    """Create loan account after approval (disbursement)."""
    data = request.get_json()
    application_id = data.get("application_id", "")

    # Load application
    app_file = LOCAL_DATA_DIR / "applications" / f"{application_id}.json"
    if not app_file.exists():
        return jsonify({"error": "Application not found"}), 404

    with open(app_file) as f:
        app_data = json.load(f)

    loan_data = {
        "loan_amount": data.get("loan_amount", app_data.get("loan_amnt", 200000)),
        "interest_rate": data.get("interest_rate", app_data.get("loan_int_rate", 10.0)),
        "tenure_months": data.get("tenure_months", 36),
        "emi_date": data.get("emi_date", 5),
        "salary_date": data.get("salary_date", 1),
        "disbursement_date": datetime.now().strftime("%Y-%m-%d"),
        "customer_name": app_data.get("full_name", ""),
        "bank_account": "XXXX" + str(uuid.uuid4().hex[:8])
    }

    loan = loan_tracker.create_loan_account(application_id, loan_data)
    return jsonify(loan)


@app.route("/api/loans", methods=["GET"])
def get_all_loans():
    """Get all loan accounts."""
    loans = loan_tracker.get_all_loans()
    return jsonify({"loans": loans, "total": len(loans)})


@app.route("/api/loans/<loan_id>", methods=["GET"])
def get_loan_details(loan_id):
    """Get detailed loan info with tracking."""
    summary = loan_tracker.get_loan_summary(loan_id)
    if "error" in summary:
        return jsonify(summary), 404
    return jsonify(summary)


@app.route("/api/loans/<loan_id>/pay", methods=["POST"])
def record_emi_payment(loan_id):
    """Record an EMI payment."""
    data = request.get_json()
    emi_number = data.get("emi_number", 1)
    payment_data = {
        "status": data.get("status", "PAID"),
        "paid_date": data.get("paid_date", datetime.now().strftime("%Y-%m-%d"))
    }
    result = loan_tracker.record_payment(loan_id, emi_number, payment_data)
    return jsonify(result)


@app.route("/api/loans/<loan_id>/simulate", methods=["POST"])
def simulate_payments(loan_id):
    """Simulate multiple months of payments for demo."""
    data = request.get_json()
    months = data.get("months", 6)

    import random
    results = []
    for i in range(1, months + 1):
        # Simulate realistic payment patterns
        rand = random.random()
        if rand < 0.70:
            status = "PAID"  # 70% on time
            days_offset = random.randint(-2, 3)
        elif rand < 0.90:
            status = "PAID"  # 20% late
            days_offset = random.randint(5, 15)
        else:
            status = "BOUNCED"  # 10% bounce
            days_offset = 0

        loan = loan_tracker._load_loan(loan_id)
        if not loan:
            break

        emi_entry = loan["schedule"][i - 1]
        due_date = datetime.strptime(emi_entry["due_date"], "%Y-%m-%d")
        paid_date = (due_date + timedelta(days=days_offset)).strftime("%Y-%m-%d")

        result = loan_tracker.record_payment(loan_id, i, {
            "status": status,
            "paid_date": paid_date
        })
        results.append(result)

    return jsonify({"simulated_months": months, "results": results})


@app.route("/api/emi-calculator", methods=["POST"])
def emi_calculator():
    """Calculate EMI and amortization."""
    data = request.get_json()
    principal = float(data.get("loan_amount", 0))
    rate = float(data.get("interest_rate", 10)) / (12 * 100)
    tenure = int(data.get("tenure_months", 36))

    if rate > 0 and principal > 0:
        emi = principal * rate * ((1 + rate) ** tenure) / ((1 + rate) ** tenure - 1)
    else:
        emi = principal / tenure if tenure > 0 else 0

    total_payable = emi * tenure
    total_interest = total_payable - principal

    return jsonify({
        "loan_amount": principal,
        "interest_rate": float(data.get("interest_rate", 10)),
        "tenure_months": tenure,
        "emi_amount": round(emi, 2),
        "total_payable": round(total_payable, 2),
        "total_interest": round(total_interest, 2),
        "interest_to_principal_ratio": round(total_interest / principal * 100, 1) if principal > 0 else 0
    })


@app.route("/api/applications/upload-document", methods=["POST"])
def upload_document():
    """Upload a document (saved locally)."""
    application_id = request.form.get("application_id")
    document_type = request.form.get("document_type")
    file = request.files.get("file")

    if not all([application_id, document_type, file]):
        return jsonify({"error": "application_id, document_type, and file required"}), 400

    # Save locally
    doc_dir = LOCAL_DATA_DIR / "documents" / application_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{document_type}_{uuid.uuid4().hex[:6]}{Path(file.filename).suffix}"
    file.save(doc_dir / filename)

    return jsonify({
        "status": "uploaded",
        "application_id": application_id,
        "document_type": document_type,
        "filename": filename,
        "message": f"{document_type} uploaded successfully."
    })


@app.route("/api/cibil/check", methods=["POST"])
def cibil_check():
    """CIBIL credit check (mock)."""
    data = request.get_json()
    pan = data.get("pan_number", "")
    consent = data.get("consent", False)

    if not pan:
        return jsonify({"error": "pan_number is required"}), 400
    if not consent:
        return jsonify({"error": "Customer consent is required"}), 400

    report = cibil_service.get_credit_report(pan, consent=True)
    return jsonify(report)


@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    """Get summary of all decisions."""
    decisions_dir = LOCAL_DATA_DIR / "decisions"
    total = approved = rejected = review = 0

    for f in decisions_dir.glob("*.json"):
        try:
            with open(f) as file:
                data = json.load(file)
                total += 1
                if data.get("decision") == "APPROVED":
                    approved += 1
                elif data.get("decision") == "REJECTED":
                    rejected += 1
                else:
                    review += 1
        except Exception:
            continue

    return jsonify({
        "total_applications": total,
        "approved": approved,
        "rejected": rejected,
        "manual_review": review,
        "approval_rate": round(approved / total * 100, 2) if total > 0 else 0,
        "timestamp": datetime.now().isoformat()
    })


# ============================================================
# ML PREDICTION
# ============================================================

FEATURE_COLUMNS = [
    "person_age", "person_income", "person_emp_exp", "loan_amnt",
    "loan_int_rate", "loan_percent_income", "cb_person_cred_hist_length",
    "person_gender", "employment_type", "person_home_ownership",
    "loan_intent", "account_type", "person_education",
    "previous_loan_defaults_on_file"
]


def make_prediction(application_data: dict, cibil_report: dict = None) -> dict:
    """Make loan prediction using deterministic rules first, then the ML model.

    Approval policy (decides BEFORE the ML model so strong profiles are not
    rejected by model quirks):
      - Hard REJECT: CIBIL < 500, OR prior defaults on file, OR loan > 50% of income.
      - APPROVE:     CIBIL >= 700 AND loan <= 40% of income AND no defaults
                     AND annual income >= Rs.2,00,000.
      - Otherwise:   fall through to the ML model, then MANUAL_REVIEW.
    """
    model = get_model()

    features = {col: application_data.get(col, 0) for col in FEATURE_COLUMNS}

    # --- Gather the signals used by the deterministic policy ---
    cibil_score = None
    if cibil_report and cibil_report.get("status") == "success":
        cibil_score = cibil_report.get("credit_score", {}).get("score", 0)
        defaults = cibil_report.get("payment_history", {}).get("defaults", 0)
        if defaults > 0:
            features["previous_loan_defaults_on_file"] = "Yes"

    try:
        loan_pct = float(application_data.get("loan_percent_income", 0) or 0)
    except (TypeError, ValueError):
        loan_pct = 0.0
    try:
        income = float(application_data.get("person_income", 0) or 0)
    except (TypeError, ValueError):
        income = 0.0
    has_defaults = (
        str(application_data.get("previous_loan_defaults_on_file", "No")).strip().lower() == "yes"
        or features.get("previous_loan_defaults_on_file") == "Yes"
    )

    # --- Hard reject rules ---
    if cibil_score is not None and cibil_score < 500:
        return {"decision": "REJECTED", "confidence": 0.92, "method": "rule_hard_reject_cibil"}
    if has_defaults:
        return {"decision": "REJECTED", "confidence": 0.88, "method": "rule_hard_reject_default"}
    if loan_pct > 0.5:
        return {"decision": "REJECTED", "confidence": 0.85, "method": "rule_hard_reject_loan_ratio"}

    # --- Approve rule for strong profiles ---
    cibil_ok = (cibil_score is None) or (cibil_score >= 700)
    if cibil_ok and loan_pct <= 0.4 and loan_pct >= 0 and income >= 200000:
        confidence = 0.90
        if cibil_score and cibil_score >= 750:
            confidence = 0.95
        return {"decision": "APPROVED", "confidence": confidence, "method": "rule_approve"}

    # ML Model prediction
    if model is not None:
        try:
            df = pd.DataFrame([features])
            prediction = model.predict(df)[0]
            probabilities = model.predict_proba(df)[0]
            confidence = float(probabilities[prediction])

            # CIBIL score adjustment
            if cibil_score:
                if cibil_score >= 750:
                    confidence = min(1.0, confidence + 0.05)
                elif cibil_score < 600:
                    confidence = max(0.0, confidence - 0.1)

            # Decision thresholds
            if prediction == 1 and confidence >= 0.85:
                decision = "APPROVED"
            elif prediction == 0 and confidence >= 0.80:
                decision = "REJECTED"
            else:
                decision = "MANUAL_REVIEW"

            return {"decision": decision, "confidence": confidence, "method": "ml_model"}

        except Exception as e:
            print(f"  ML prediction error: {e}")

    # Rule-based fallback
    return rule_based_prediction(features, cibil_score)


def rule_based_prediction(features: dict, cibil_score: int = None) -> dict:
    """Fallback when model unavailable."""
    loan_pct = features.get("loan_percent_income", 0)
    income = features.get("person_income", 0)
    defaults = features.get("previous_loan_defaults_on_file", "No")

    if defaults == "Yes":
        return {"decision": "REJECTED", "confidence": 0.80, "method": "rule_based"}
    if loan_pct > 0.4:
        return {"decision": "REJECTED", "confidence": 0.75, "method": "rule_based"}
    if cibil_score and cibil_score < 600:
        return {"decision": "REJECTED", "confidence": 0.78, "method": "rule_based"}
    if loan_pct < 0.2 and income > 500000 and (cibil_score is None or cibil_score >= 700):
        return {"decision": "APPROVED", "confidence": 0.82, "method": "rule_based"}

    return {"decision": "MANUAL_REVIEW", "confidence": 0.55, "method": "rule_based"}


def get_next_steps(decision: str) -> list:
    if decision == "APPROVED":
        return [
            "Upload required documents (Aadhaar, PAN, Salary Slips, Bank Statement)",
            "Complete e-KYC verification",
            "Sign the digital loan agreement",
            "Loan will be disbursed within 24-48 hours after verification"
        ]
    elif decision == "REJECTED":
        return [
            "Review the rejection reasons above",
            "You may reapply after 90 days",
            "Improve your CIBIL score by timely repayments",
            "Request manual review by contacting support"
        ]
    else:
        return [
            "Upload all required documents to speed up review",
            "Our team will review within 2-3 business days",
            "You will receive SMS/email notification",
            "Contact support for any questions"
        ]


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    print("")
    print("=" * 60)
    print("  LOAN APPROVAL SYSTEM - LOCAL MODE")
    print("=" * 60)
    print("")
    print("  Loading ML model...")
    get_model()
    print("")
    print("  Server starting on: http://localhost:8000")
    print("")
    print("  Open in your browser:")
    print("    → http://localhost:8000")
    print("")
    print("  API Endpoints:")
    print("    POST /api/applications/submit")
    print("    GET  /api/applications/<id>/status")
    print("    POST /api/applications/upload-document")
    print("    POST /api/cibil/check")
    print("    GET  /api/dashboard/summary")
    print("    GET  /health")
    print("")
    print("  Data stored in: ./local_data/")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print("")

    app.run(host="0.0.0.0", port=8000, debug=True)
