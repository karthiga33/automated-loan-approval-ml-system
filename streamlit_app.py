"""
Loan Approval System - STREAMLIT VERSION
-----------------------------------------
Single-file Streamlit app that reuses the existing service modules
(CIBIL, explainability, validator) and the trained ML pipeline.

No AWS, no separate backend. Everything runs inside this app.

Run locally:
    pip install -r requirements-streamlit.txt
    streamlit run streamlit_app.py

Deploy (free):
    Push to GitHub, then on https://share.streamlit.io point a new app at
    this repo with "streamlit_app.py" as the main file.

NOTE ON PERSISTENCE:
    Streamlit Community Cloud has an ephemeral filesystem. Applications are
    kept in st.session_state for the life of the session so Track works, and
    also written to ./local_data when the disk is writable (local runs). On
    Streamlit Cloud the files may reset on restart - fine for a demo.
"""
import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
import streamlit as st

# Make the service package importable regardless of working directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.cibil_service import CIBILService
from services.explainability import LoanExplainabilityService
from services.input_validator import LoanApplicationValidator

# ============================================================
# CONFIG
# ============================================================
st.set_page_config(
    page_title="Loan Approval System",
    page_icon="🏦",
    layout="wide",
)

LOCAL_DATA_DIR = Path(BASE_DIR) / "local_data"
MODEL_PATH = LOCAL_DATA_DIR / "models" / "loan_approval_pipeline.pkl"
DATA_PATH = Path(BASE_DIR) / "data" / "loan-data.csv"

FEATURE_COLUMNS = [
    "person_age", "person_income", "person_emp_exp", "loan_amnt",
    "loan_int_rate", "loan_percent_income", "cb_person_cred_hist_length",
    "person_gender", "employment_type", "person_home_ownership",
    "loan_intent", "account_type", "person_education",
    "previous_loan_defaults_on_file",
]

# Validator option lists (kept in sync with services/input_validator.py)
GENDERS = ["Male", "Female", "Other"]
EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Self-employed", "Contract", "Freelance"]
HOME_OWNERSHIP = ["OWN", "RENT", "MORTGAGE", "OTHER"]
LOAN_INTENTS = ["PERSONAL", "EDUCATION", "MEDICAL", "HOME", "VEHICLE", "BUSINESS", "DEBTCONSOLIDATION"]
ACCOUNT_TYPES = ["Checking", "Savings", "Both"]
EDUCATION = ["High School", "Associate", "Bachelor", "Master", "Doctorate"]

# ============================================================
# SERVICES (cached)
# ============================================================
@st.cache_resource(show_spinner=False)
def get_services():
    return {
        "cibil": CIBILService(mode="mock"),
        "explain": LoanExplainabilityService(),
        "validator": LoanApplicationValidator(),
    }


@st.cache_resource(show_spinner="Loading ML model...")
def get_model():
    """Load the trained pipeline, training it from CSV if needed."""
    if MODEL_PATH.exists():
        try:
            return joblib.load(MODEL_PATH)
        except Exception as e:
            st.warning(f"Could not load saved model ({e}); retraining.")

    if not DATA_PATH.exists():
        return None

    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, OrdinalEncoder
    from sklearn.compose import ColumnTransformer

    df = pd.read_csv(DATA_PATH)
    numeric = ['person_age', 'person_income', 'person_emp_exp', 'loan_amnt',
               'loan_int_rate', 'loan_percent_income', 'cb_person_cred_hist_length']
    categorical = ['person_gender', 'employment_type', 'person_home_ownership',
                   'loan_intent', 'account_type', 'person_education',
                   'previous_loan_defaults_on_file']
    target = 'loan_status'

    numeric = [c for c in numeric if c in df.columns]
    categorical = [c for c in categorical if c in df.columns]
    if target not in df.columns:
        return None

    X = df[numeric + categorical].copy()
    y = df[target].copy()
    for c in numeric:
        X[c] = X[c].fillna(X[c].median())
    for c in categorical:
        X[c] = X[c].fillna('Unknown')

    pre = ColumnTransformer([
        ('num', StandardScaler(), numeric),
        ('cat', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1), categorical),
    ])
    pipe = Pipeline([
        ('preprocessor', pre),
        ('classifier', RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)),
    ])
    X_train, _, y_train, _ = train_test_split(X, y, test_size=0.2, random_state=42)
    pipe.fit(X_train, y_train)
    try:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipe, MODEL_PATH)
    except Exception:
        pass  # read-only FS on cloud is fine; model stays in memory
    return pipe


# ============================================================
# PREDICTION  (same policy as app_local.make_prediction)
# ============================================================
def make_prediction(application_data: dict, cibil_report: dict = None) -> dict:
    model = get_model()
    features = {col: application_data.get(col, 0) for col in FEATURE_COLUMNS}

    cibil_score = None
    if cibil_report and cibil_report.get("status") == "success":
        cibil_score = cibil_report.get("credit_score", {}).get("score", 0)
        if cibil_report.get("payment_history", {}).get("defaults", 0) > 0:
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

    # Hard reject rules
    if cibil_score is not None and cibil_score < 500:
        return {"decision": "REJECTED", "confidence": 0.92, "method": "rule_hard_reject_cibil"}
    if has_defaults:
        return {"decision": "REJECTED", "confidence": 0.88, "method": "rule_hard_reject_default"}
    if loan_pct > 0.5:
        return {"decision": "REJECTED", "confidence": 0.85, "method": "rule_hard_reject_loan_ratio"}

    # Approve strong profiles
    cibil_ok = (cibil_score is None) or (cibil_score >= 700)
    if cibil_ok and 0 <= loan_pct <= 0.4 and income >= 200000:
        conf = 0.95 if (cibil_score and cibil_score >= 750) else 0.90
        return {"decision": "APPROVED", "confidence": conf, "method": "rule_approve"}

    # ML model
    if model is not None:
        try:
            df = pd.DataFrame([features])
            pred = model.predict(df)[0]
            proba = model.predict_proba(df)[0]
            conf = float(proba[pred])
            if cibil_score:
                if cibil_score >= 750:
                    conf = min(1.0, conf + 0.05)
                elif cibil_score < 600:
                    conf = max(0.0, conf - 0.1)
            if pred == 1 and conf >= 0.85:
                decision = "APPROVED"
            elif pred == 0 and conf >= 0.80:
                decision = "REJECTED"
            else:
                decision = "MANUAL_REVIEW"
            return {"decision": decision, "confidence": conf, "method": "ml_model"}
        except Exception as e:
            st.warning(f"Model prediction error, using rules: {e}")

    # Rule-based fallback
    if loan_pct > 0.4:
        return {"decision": "REJECTED", "confidence": 0.75, "method": "rule_based"}
    if cibil_score and cibil_score < 600:
        return {"decision": "REJECTED", "confidence": 0.78, "method": "rule_based"}
    return {"decision": "MANUAL_REVIEW", "confidence": 0.55, "method": "rule_based"}


def get_next_steps(decision: str) -> list:
    if decision == "APPROVED":
        return [
            "Upload required documents (Aadhaar, PAN, Salary Slips, Bank Statement)",
            "Complete e-KYC verification",
            "Sign the digital loan agreement",
            "Loan will be disbursed within 24-48 hours after verification",
        ]
    if decision == "REJECTED":
        return [
            "Review the rejection reasons above",
            "You may reapply after 90 days",
            "Improve your CIBIL score by timely repayments",
            "Request manual review by contacting support",
        ]
    return [
        "Upload all required documents to speed up review",
        "Our team will review within 2-3 business days",
        "You will receive SMS/email notification",
        "Contact support for any questions",
    ]


def save_application(sanitized: dict, response: dict):
    """Keep in session for Track, and try to persist to disk."""
    st.session_state.setdefault("applications", {})
    st.session_state["applications"][response["application_id"]] = {
        "application": sanitized,
        "decision": response,
    }
    try:
        (LOCAL_DATA_DIR / "applications").mkdir(parents=True, exist_ok=True)
        (LOCAL_DATA_DIR / "decisions").mkdir(parents=True, exist_ok=True)
        with open(LOCAL_DATA_DIR / "applications" / f"{response['application_id']}.json", "w") as f:
            json.dump(sanitized, f, indent=2)
        with open(LOCAL_DATA_DIR / "decisions" / f"{response['application_id']}.json", "w") as f:
            json.dump(response, f, indent=2)
    except Exception:
        pass


# ============================================================
# EMI + ELIGIBILITY (same math as app_local)
# ============================================================
def calculate_emi(principal, annual_rate, tenure_months):
    r = annual_rate / 12 / 100
    if r == 0:
        emi = principal / tenure_months
    else:
        emi = principal * r * ((1 + r) ** tenure_months) / (((1 + r) ** tenure_months) - 1)
    total = emi * tenure_months
    return emi, total, total - principal


def check_eligibility(income, age, cibil_score):
    available_for_emi = max(0, income * 0.50)
    max_tenure_years = max(1, min(30, 60 - age))
    max_tenure_months = max_tenure_years * 12
    rate = 8.5 / 12 / 100
    if available_for_emi > 0 and rate > 0:
        max_loan = available_for_emi * (((1 + rate) ** max_tenure_months) - 1) / (rate * ((1 + rate) ** max_tenure_months))
    else:
        max_loan = 0
    if cibil_score >= 750:
        mult, risk, offered = 1.0, "LOW", 8.5
    elif cibil_score >= 700:
        mult, risk, offered = 0.85, "MODERATE", 10.5
    elif cibil_score >= 650:
        mult, risk, offered = 0.65, "HIGH", 13.0
    else:
        mult, risk, offered = 0.3, "VERY HIGH", 16.0
    max_loan_adj = max_loan * mult
    return {
        "eligible": max_loan_adj > 50000,
        "max_loan_amount": round(max_loan_adj),
        "max_emi_affordable": round(available_for_emi),
        "suggested_interest_rate": offered,
        "max_tenure_months": max_tenure_months,
        "risk_category": risk,
    }


# ============================================================
# UI
# ============================================================
def page_apply():
    st.header("Apply for a Loan")
    svc = get_services()

    with st.form("loan_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            full_name = st.text_input("Full Name", "Rahul Sharma")
            person_age = st.number_input("Age", 18, 75, 32)
            person_gender = st.selectbox("Gender", GENDERS)
            person_education = st.selectbox("Education", EDUCATION, index=2)
            pan_number = st.text_input("PAN Number", "ABCDE1234F")
        with c2:
            person_income = st.number_input("Annual Income (₹)", 0, 100_000_000, 1_200_000, step=50_000)
            person_emp_exp = st.number_input("Employment Experience (years)", 0, 50, 6)
            employment_type = st.selectbox("Employment Type", EMPLOYMENT_TYPES)
            person_home_ownership = st.selectbox("Home Ownership", HOME_OWNERSHIP, index=1)
            aadhaar_number = st.text_input("Aadhaar Number", "123456789012")
        with c3:
            loan_amnt = st.number_input("Loan Amount (₹)", 0, 100_000_000, 300_000, step=10_000)
            loan_int_rate = st.number_input("Interest Rate (%)", 0.0, 40.0, 10.5, step=0.5)
            loan_intent = st.selectbox("Loan Purpose", LOAN_INTENTS)
            account_type = st.selectbox("Account Type", ACCOUNT_TYPES, index=1)
            cb_person_cred_hist_length = st.number_input("Credit History (years)", 0, 50, 8)

        colA, colB = st.columns(2)
        with colA:
            previous_loan_defaults_on_file = st.selectbox("Previous Loan Defaults", ["No", "Yes"])
        with colB:
            consent = st.checkbox("I consent to a CIBIL credit check", value=True)

        submitted = st.form_submit_button("Submit Application", use_container_width=True)

    if not submitted:
        return

    data = {
        "full_name": full_name, "person_age": person_age, "person_gender": person_gender,
        "person_income": person_income, "person_emp_exp": person_emp_exp,
        "employment_type": employment_type, "person_home_ownership": person_home_ownership,
        "loan_amnt": loan_amnt, "loan_int_rate": loan_int_rate, "loan_intent": loan_intent,
        "person_education": person_education, "account_type": account_type,
        "previous_loan_defaults_on_file": previous_loan_defaults_on_file,
        "cb_person_cred_hist_length": cb_person_cred_hist_length,
        "pan_number": pan_number, "aadhaar_number": aadhaar_number,
        "consent_cibil_check": consent,
    }

    is_valid, errors, sanitized = svc["validator"].validate_application(data)
    if not is_valid:
        st.error("Please fix the following:")
        for e in errors:
            st.write(f"- **{e.field}**: {e.message}")
        return

    application_id = f"LA-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    sanitized["application_id"] = application_id
    sanitized["submission_timestamp"] = datetime.now().isoformat()

    cibil_report = None
    if sanitized.get("consent_cibil_check"):
        cibil_report = svc["cibil"].get_credit_report(sanitized["pan_number"], consent=True)

    result = make_prediction(sanitized, cibil_report)
    explanation = svc["explain"].generate_explanation(
        application_data=sanitized,
        decision=result["decision"],
        confidence=result["confidence"],
        cibil_report=cibil_report,
        verification_result=None,
    )
    cibil_score = None
    if cibil_report and cibil_report.get("status") == "success":
        cibil_score = cibil_report.get("credit_score", {}).get("score")

    response = {
        "status": "processed",
        "application_id": application_id,
        "decision": result["decision"],
        "confidence": round(result["confidence"] * 100, 1),
        "explanation": explanation,
        "cibil_score": cibil_score,
        "next_steps": get_next_steps(result["decision"]),
        "timestamp": datetime.now().isoformat(),
    }
    save_application(sanitized, response)
    render_decision(response)


def render_decision(response: dict):
    decision = response["decision"]
    conf = response["confidence"]
    if decision == "APPROVED":
        st.success(f"### ✅ Application Approved  —  Confidence {conf}%")
    elif decision == "REJECTED":
        st.error(f"### ❌ Application Not Approved  —  Confidence {conf}%")
    else:
        st.warning(f"### 🔍 Manual Review Required  —  Confidence {conf}%")

    st.caption(f"Application ID: {response['application_id']}")

    m1, m2 = st.columns(2)
    with m1:
        if response.get("cibil_score"):
            st.metric("CIBIL Credit Score", f"{response['cibil_score']} / 900")
    with m2:
        st.metric("Decision Confidence", f"{conf}%")

    left, right = st.columns(2)
    with left:
        st.subheader("Decision Reasons")
        for r in response["explanation"].get("primary_reasons", []):
            st.write(f"- {r}")
        pos = response["explanation"].get("positive_factors", [])
        if pos:
            with st.expander("Positive factors"):
                for p in pos:
                    st.write(f"- {p}")
    with right:
        st.subheader("Next Steps")
        for s in response["next_steps"]:
            st.write(f"- {s}")


def page_emi():
    st.header("EMI Calculator")
    c1, c2, c3 = st.columns(3)
    amount = c1.number_input("Loan Amount (₹)", 10000, 100_000_000, 500_000, step=10_000)
    rate = c2.number_input("Interest Rate (%)", 1.0, 40.0, 10.0, step=0.5)
    tenure = c3.number_input("Tenure (months)", 1, 360, 36)
    emi, total, interest = calculate_emi(amount, rate, tenure)
    a, b, c = st.columns(3)
    a.metric("Monthly EMI", f"₹{emi:,.0f}")
    b.metric("Total Payment", f"₹{total:,.0f}")
    c.metric("Total Interest", f"₹{interest:,.0f}")

    # Amortization schedule
    r = rate / 12 / 100
    bal = amount
    rows = []
    for m in range(1, int(tenure) + 1):
        ic = bal * r
        pc = emi - ic
        bal = max(0, bal - pc)
        rows.append({"Month": m, "EMI": round(emi), "Principal": round(pc), "Interest": round(ic), "Balance": round(bal)})
    with st.expander("Repayment schedule"):
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def page_eligibility():
    st.header("Eligibility Check")
    c1, c2, c3 = st.columns(3)
    income = c1.number_input("Monthly Income (₹)", 0, 10_000_000, 80_000, step=5_000)
    age = c2.number_input("Age", 18, 75, 30)
    cibil = c3.number_input("CIBIL Score", 300, 900, 760)
    if st.button("Check Eligibility", use_container_width=True):
        if income <= 0:
            st.error("Monthly income is required")
            return
        res = check_eligibility(income, age, cibil)
        if res["eligible"]:
            st.success("You're eligible!")
        else:
            st.error("Not eligible with the current profile")
        a, b, c, d = st.columns(4)
        a.metric("Max Loan", f"₹{res['max_loan_amount']:,.0f}")
        b.metric("Max EMI", f"₹{res['max_emi_affordable']:,.0f}")
        c.metric("Rate", f"{res['suggested_interest_rate']}%")
        d.metric("Risk", res["risk_category"])


def page_track():
    st.header("Track Application")
    apps = st.session_state.get("applications", {})
    app_id = st.text_input("Application ID", placeholder="LA-YYYYMMDD-XXXXXXXX")
    if st.button("Track"):
        rec = apps.get(app_id.strip())
        if not rec:
            st.error("Application not found in this session. (Streamlit Cloud resets data on restart.)")
            return
        render_decision(rec["decision"])

    if apps:
        with st.expander("Applications submitted this session"):
            for aid, rec in apps.items():
                st.write(f"- **{aid}** → {rec['decision']['decision']}")


def main():
    st.title("🏦 Automated Loan Approval System")
    page = st.sidebar.radio(
        "Navigate",
        ["Apply for Loan", "EMI Calculator", "Eligibility Check", "Track Application"],
    )
    st.sidebar.info("ML-powered loan decisions. Demo mode — data resets on restart.")

    if page == "Apply for Loan":
        page_apply()
    elif page == "EMI Calculator":
        page_emi()
    elif page == "Eligibility Check":
        page_eligibility()
    else:
        page_track()


if __name__ == "__main__":
    main()
