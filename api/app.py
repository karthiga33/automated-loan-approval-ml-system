"""
Loan Approval System - Main API Application
Production-ready Flask API with authentication, validation, and explainability.
"""
import os
import sys
import json
import uuid
import boto3
import joblib
import pandas as pd
from io import BytesIO
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from functools import wraps

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    AWS_REGION, S3_BUCKET_NAME, DYNAMODB_TABLE, MODEL_KEY,
    FEATURE_COLUMNS, ML_CONFIDENCE_AUTO_APPROVE, ML_CONFIDENCE_AUTO_REJECT,
    API_PORT, CIBIL_MODE, RATE_LIMIT_PER_MINUTE
)
from services.cibil_service import CIBILService
from services.document_verification import DocumentVerificationService
from services.explainability import LoanExplainabilityService
from services.input_validator import LoanApplicationValidator
from services.auth_service import (
    generate_token, verify_token, check_rate_limit,
    hash_password, verify_password, require_auth
)

app = Flask(__name__, static_folder="../frontend/static", static_url_path="/static")

# Initialize services
cibil_service = CIBILService(mode=CIBIL_MODE)
doc_service = DocumentVerificationService(region=AWS_REGION, bucket_name=S3_BUCKET_NAME)
explainability_service = LoanExplainabilityService()
validator = LoanApplicationValidator()

# AWS clients
s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

# ML Model cache
MODEL_CACHE = {}


def get_model():
    """Load ML model from S3 with caching."""
    if "pipeline" not in MODEL_CACHE:
        try:
            print("Loading ML model from S3...")
            model_obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=MODEL_KEY)
            model_bytes = BytesIO(model_obj["Body"].read())
            MODEL_CACHE["pipeline"] = joblib.load(model_bytes)
            print("ML model loaded successfully")
        except Exception as e:
            print(f"Could not load model from S3: {e}")
            MODEL_CACHE["pipeline"] = None
    return MODEL_CACHE["pipeline"]


def rate_limit(f):
    """Rate limiting decorator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr or "unknown"
        if not check_rate_limit(client_ip, RATE_LIMIT_PER_MINUTE):
            return jsonify({
                "error": "Rate limit exceeded. Please try again later."
            }), 429
        return f(*args, **kwargs)
    return decorated


# ============================================================
# PUBLIC ROUTES (No auth required)
# ============================================================

@app.route("/")
def index():
    """Serve the customer portal."""
    return send_from_directory("../frontend", "index.html")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "Loan Approval System",
        "model_loaded": MODEL_CACHE.get("pipeline") is not None,
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    })


# ============================================================
# AUTH ROUTES
# ============================================================

@app.route("/api/auth/register", methods=["POST"])
@rate_limit
def register():
    """Register a new applicant account."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body required"}), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    full_name = data.get("full_name", "")

    if not email or not password or not full_name:
        return jsonify({"error": "email, password, and full_name are required"}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    # Generate user ID and hash password
    user_id = str(uuid.uuid4())
    hashed_pw, salt = hash_password(password)

    # Store user (in production, use DynamoDB or RDS)
    # For now, generate token directly
    token = generate_token(user_id, role="applicant")

    return jsonify({
        "message": "Registration successful",
        "user_id": user_id,
        "token": token,
        "full_name": full_name
    }), 201


@app.route("/api/auth/login", methods=["POST"])
@rate_limit
def login():
    """Login and get JWT token."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body required"}), 400

    email = data.get("email", "")
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    # For demo: generate token (in production, verify against stored credentials)
    user_id = str(uuid.uuid4())
    token = generate_token(user_id, role="applicant")

    return jsonify({
        "message": "Login successful",
        "token": token,
        "user_id": user_id
    })


# ============================================================
# LOAN APPLICATION ROUTES
# ============================================================

@app.route("/api/applications/submit", methods=["POST"])
@rate_limit
def submit_application():
    """
    Submit a new loan application.
    This is the main entry point for the loan approval process.
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Application data required"}), 400

    # Step 1: Validate input
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
    sanitized_data["status"] = "submitted"

    # Step 3: Store application in S3
    try:
        s3_key = f"applications/{application_id}/application.json"
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=json.dumps(sanitized_data, indent=2),
            ContentType="application/json"
        )
    except Exception as e:
        print(f"S3 storage error: {e}")
        # Continue even if S3 fails - process locally

    # Step 4: CIBIL credit check (if consent given)
    cibil_report = None
    if sanitized_data.get("consent_cibil_check"):
        cibil_report = cibil_service.get_credit_report(
            pan_number=sanitized_data["pan_number"],
            consent=True
        )

    # Step 5: ML Prediction
    prediction_result = _make_prediction(sanitized_data, cibil_report)

    # Step 6: Generate explanation
    explanation = explainability_service.generate_explanation(
        application_data=sanitized_data,
        decision=prediction_result["decision"],
        confidence=prediction_result["confidence"],
        cibil_report=cibil_report,
        verification_result=None  # Documents not yet verified at submission
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
        "next_steps": _get_next_steps(prediction_result["decision"]),
        "timestamp": datetime.now().isoformat()
    }

    # Step 8: Store decision in DynamoDB
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        table.put_item(Item={
            "application_id": application_id,
            "date": datetime.now().strftime("%Y%m%d"),
            "decision": prediction_result["decision"],
            "confidence": str(prediction_result["confidence"]),
            "loan_amount": str(sanitized_data.get("loan_amnt", 0)),
            "person_income": str(sanitized_data.get("person_income", 0)),
            "cibil_score": str(cibil_report.get("credit_score", {}).get("score", "N/A")) if cibil_report else "N/A",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        print(f"DynamoDB error: {e}")

    return jsonify(response), 200


@app.route("/api/applications/<application_id>/status", methods=["GET"])
@rate_limit
def get_application_status(application_id):
    """Get the status of a submitted application."""
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        # Query by application_id
        response = table.get_item(
            Key={
                "application_id": application_id,
                "date": datetime.now().strftime("%Y%m%d")
            }
        )
        item = response.get("Item")
        if item:
            return jsonify({
                "application_id": application_id,
                "decision": item.get("decision"),
                "confidence": item.get("confidence"),
                "timestamp": item.get("timestamp")
            })
        else:
            return jsonify({"error": "Application not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/applications/upload-document", methods=["POST"])
@rate_limit
def upload_document():
    """Upload a document for verification."""
    application_id = request.form.get("application_id")
    document_type = request.form.get("document_type")
    file = request.files.get("file")

    if not all([application_id, document_type, file]):
        return jsonify({
            "error": "application_id, document_type, and file are required"
        }), 400

    if document_type not in ["aadhaar", "pan", "salary_slip", "bank_statement", "photograph"]:
        return jsonify({
            "error": "Invalid document_type. Must be: aadhaar, pan, salary_slip, bank_statement, photograph"
        }), 400

    # Check file size (10MB max)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 10 * 1024 * 1024:
        return jsonify({"error": "File size exceeds 10MB limit"}), 400

    # Upload to S3
    try:
        s3_key = f"applications/{application_id}/documents/{document_type}_{uuid.uuid4().hex[:8]}"
        s3.upload_fileobj(
            file,
            S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={"ContentType": file.content_type}
        )

        return jsonify({
            "status": "uploaded",
            "application_id": application_id,
            "document_type": document_type,
            "s3_key": s3_key,
            "message": f"{document_type} uploaded successfully. Verification will begin shortly."
        })

    except Exception as e:
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500


@app.route("/api/documents/requirements", methods=["POST"])
@rate_limit
def get_document_requirements():
    """Get required documents based on loan type and employment."""
    data = request.get_json()
    loan_type = data.get("loan_intent", "PERSONAL")
    employment_type = data.get("employment_type", "Full-time")

    from services.indian_document_verification import IndianDocumentVerificationService
    doc_service_india = IndianDocumentVerificationService(
        region=AWS_REGION, bucket_name=S3_BUCKET_NAME
    )
    requirements = doc_service_india.get_required_documents(loan_type, employment_type)

    return jsonify({
        "loan_type": loan_type,
        "employment_type": employment_type,
        "required_documents": requirements,
        "total_documents": len(requirements),
        "max_file_size_mb": 10,
        "accepted_formats": ["PDF", "JPG", "JPEG", "PNG"]
    })


# ============================================================
# DASHBOARD / ANALYTICS ROUTES
# ============================================================

@app.route("/api/dashboard/summary", methods=["GET"])
@rate_limit
def dashboard_summary():
    """Get overall loan approval statistics."""
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        today = datetime.now().strftime("%Y%m%d")

        # Scan for today's records (in production, use queries with GSI)
        response = table.scan(
            FilterExpression="#d = :today",
            ExpressionAttributeNames={"#d": "date"},
            ExpressionAttributeValues={":today": today},
            Limit=1000
        )

        items = response.get("Items", [])
        total = len(items)
        approved = sum(1 for i in items if i.get("decision") == "APPROVED")
        rejected = sum(1 for i in items if i.get("decision") == "REJECTED")
        review = sum(1 for i in items if i.get("decision") == "MANUAL_REVIEW")

        return jsonify({
            "total_applications": total,
            "approved": approved,
            "rejected": rejected,
            "manual_review": review,
            "approval_rate": round(approved / total * 100, 2) if total > 0 else 0,
            "date": today,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({
            "total_applications": 0,
            "approved": 0,
            "rejected": 0,
            "manual_review": 0,
            "approval_rate": 0,
            "message": f"Could not fetch data: {str(e)}"
        })


@app.route("/api/cibil/check", methods=["POST"])
@rate_limit
def cibil_check():
    """Perform a CIBIL credit check (mock)."""
    data = request.get_json()
    pan_number = data.get("pan_number", "")
    consent = data.get("consent", False)

    if not pan_number:
        return jsonify({"error": "pan_number is required"}), 400

    if not consent:
        return jsonify({"error": "Customer consent is required for credit check"}), 400

    report = cibil_service.get_credit_report(pan_number, consent=True)
    return jsonify(report)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _make_prediction(application_data: dict, cibil_report: dict = None) -> dict:
    """
    Make loan approval prediction using ML model with rule-based fallback.
    """
    model = get_model()

    # Prepare features for model
    features = {col: application_data.get(col, 0) for col in FEATURE_COLUMNS}

    # Incorporate CIBIL data into decision
    cibil_score = None
    if cibil_report and cibil_report.get("status") == "success":
        cibil_score = cibil_report.get("credit_score", {}).get("score", 0)
        defaults = cibil_report.get("payment_history", {}).get("defaults", 0)

        # Hard reject if CIBIL is very poor
        if cibil_score < 500:
            return {
                "decision": "REJECTED",
                "confidence": 0.92,
                "method": "cibil_hard_reject"
            }

        # Update default info from CIBIL
        if defaults > 0:
            features["previous_loan_defaults_on_file"] = "Yes"

    if model is not None:
        try:
            df = pd.DataFrame([features])
            prediction = model.predict(df)[0]
            probabilities = model.predict_proba(df)[0]
            confidence = float(probabilities[prediction])

            # Apply CIBIL score adjustment
            if cibil_score:
                if cibil_score >= 750:
                    confidence = min(1.0, confidence + 0.05)
                elif cibil_score < 600:
                    confidence = max(0.0, confidence - 0.1)

            # Determine decision based on confidence thresholds
            if prediction == 1 and confidence >= ML_CONFIDENCE_AUTO_APPROVE:
                decision = "APPROVED"
            elif prediction == 0 and confidence >= ML_CONFIDENCE_AUTO_REJECT:
                decision = "REJECTED"
            else:
                decision = "MANUAL_REVIEW"

            return {
                "decision": decision,
                "confidence": confidence,
                "method": "ml_model"
            }

        except Exception as e:
            print(f"ML prediction failed: {e}")

    # Rule-based fallback
    return _rule_based_prediction(features, cibil_score)


def _rule_based_prediction(features: dict, cibil_score: int = None) -> dict:
    """Fallback rule-based prediction when ML model is unavailable."""
    loan_percent_income = features.get("loan_percent_income", 0)
    income = features.get("person_income", 0)
    defaults = features.get("previous_loan_defaults_on_file", "No")

    # Hard rejection rules
    if defaults == "Yes":
        return {"decision": "REJECTED", "confidence": 0.80, "method": "rule_based"}

    if loan_percent_income > 0.4:
        return {"decision": "REJECTED", "confidence": 0.75, "method": "rule_based"}

    if cibil_score and cibil_score < 600:
        return {"decision": "REJECTED", "confidence": 0.78, "method": "rule_based"}

    # Approval rules
    if (loan_percent_income < 0.2 and income > 500000 and
            (cibil_score is None or cibil_score >= 700)):
        return {"decision": "APPROVED", "confidence": 0.82, "method": "rule_based"}

    # Everything else needs review
    return {"decision": "MANUAL_REVIEW", "confidence": 0.55, "method": "rule_based"}


def _get_next_steps(decision: str) -> list:
    """Get next steps based on decision."""
    if decision == "APPROVED":
        return [
            "Upload required documents (Aadhaar, PAN, Salary Slips)",
            "Complete e-KYC verification",
            "Sign the digital loan agreement",
            "Loan amount will be disbursed within 24-48 hours"
        ]
    elif decision == "REJECTED":
        return [
            "Review the reasons for rejection above",
            "You may apply again after 90 days",
            "Consider improving your credit score",
            "You can request a manual review by contacting support"
        ]
    else:  # MANUAL_REVIEW
        return [
            "Your application is being reviewed by our team",
            "Upload all required documents to speed up the process",
            "You will receive a decision within 2-3 business days",
            "Contact support if you have questions"
        ]


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  LOAN APPROVAL SYSTEM - API Server")
    print("=" * 60)
    print(f"  Region:     {AWS_REGION}")
    print(f"  S3 Bucket:  {S3_BUCKET_NAME}")
    print(f"  CIBIL Mode: {CIBIL_MODE}")
    print(f"  Port:       {API_PORT}")
    print("=" * 60)
    print("  Endpoints:")
    print("    POST /api/auth/register       - Register")
    print("    POST /api/auth/login          - Login")
    print("    POST /api/applications/submit - Submit loan application")
    print("    GET  /api/applications/<id>/status")
    print("    POST /api/applications/upload-document")
    print("    POST /api/cibil/check         - Credit check")
    print("    GET  /api/dashboard/summary   - Analytics")
    print("    GET  /health                  - Health check")
    print("    GET  /                        - Customer Portal")
    print("=" * 60)

    # Try to load model at startup
    get_model()

    app.run(host="0.0.0.0", port=API_PORT, debug=False)
