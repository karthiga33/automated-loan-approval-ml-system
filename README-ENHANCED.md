# Loan Approval System - Enhanced Production Version

## Overview

Real-world automated loan approval system with:
- **ML-powered decisions** (Random Forest, 90.4% precision)
- **Document verification** (AWS Textract OCR for Aadhaar, PAN, Salary Slips)
- **CIBIL credit check** (Mock now, pluggable for real API)
- **Explainable decisions** (Clear reasons for approve/reject)
- **Customer web portal** (Apply online, instant decision)
- **Input validation** (Indian PAN, Aadhaar, phone format)
- **Security** (JWT auth, rate limiting, input sanitization)

---

## Architecture

```
Customer → Web Portal → API Gateway → Flask API
                                         │
                         ┌───────────────┼───────────────┐
                         │               │               │
                         ▼               ▼               ▼
                   Input Validator   CIBIL Check    Document OCR
                         │               │          (Textract)
                         └───────┬───────┘               │
                                 ▼                       │
                           ML Predictor ◄────────────────┘
                           (Random Forest)
                                 │
                         ┌───────┼───────┐
                         ▼       ▼       ▼
                     APPROVED  REJECTED  MANUAL REVIEW
                         │       │       │
                         ▼       ▼       ▼
                    Explainability Engine
                    (Reasons + Suggestions)
                         │
                         ▼
                   DynamoDB + S3 (Store)
                         │
                         ▼
                Customer Notification
```

---

## Project Structure (Enhanced)

```
Automated-Loan-Approval-ML-System/
├── api/
│   └── app.py                    # Main Flask API (production-ready)
├── config/
│   ├── __init__.py
│   └── settings.py               # All configuration (env-based)
├── services/
│   ├── __init__.py
│   ├── auth_service.py           # JWT authentication + rate limiting
│   ├── cibil_service.py          # CIBIL credit bureau (mock/live)
│   ├── document_verification.py  # AWS Textract OCR
│   ├── explainability.py         # Decision explanation engine
│   └── input_validator.py        # Form validation (PAN, Aadhaar, etc.)
├── frontend/
│   └── index.html                # Customer portal (apply for loan)
├── lambdas/
│   ├── lambda-loan-extractor.py
│   ├── lambda-loan-processor.py
│   ├── lambda-loan-predictor.py
│   └── lambda-document-processor.py  # NEW: OCR processing
├── infrastructure/
│   └── cloudformation.yaml       # AWS infrastructure as code
├── deploy/
│   ├── deploy-cloudshell.sh      # One-command CloudShell deployment
│   ├── deploy-ec2.sh             # EC2 API server setup
│   ├── test-system.sh            # Automated testing
│   └── cleanup.sh                # Remove all resources
├── data/
│   └── loan-data.csv             # Training data
├── notebooks/
│   ├── loan_approval_analysis.ipynb
│   └── loan_approval_production.ipynb
└── requirements/
    ├── requirements.txt
    ├── requirements-ec2.txt
    └── requirements-lambda.txt
```

---

## Quick Start (CloudShell Deployment)

### Step 1: Open AWS CloudShell
Log into AWS Console → Click CloudShell icon (top bar)

### Step 2: Clone & Deploy
```bash
git clone https://github.com/YOUR_REPO/Automated-Loan-Approval-ML-System.git
cd Automated-Loan-Approval-ML-System
chmod +x deploy/deploy-cloudshell.sh
./deploy/deploy-cloudshell.sh
```

### Step 3: Deploy EC2 API (for web portal)
```bash
# Launch t2.micro EC2 (free tier) from AWS Console
# SSH in, then:
chmod +x deploy/deploy-ec2.sh
./deploy/deploy-ec2.sh
```

### Step 4: Test
```bash
chmod +x deploy/test-system.sh
./deploy/test-system.sh http://YOUR_EC2_IP:8000
```

### Step 5: Open Customer Portal
```
http://YOUR_EC2_IP:8000/
```

---

## Real-World Loan Flow

1. **Application** → Customer fills form on web portal
2. **Validation** → System validates PAN, Aadhaar, income, age
3. **CIBIL Check** → Pull credit score (mock/real)
4. **ML Decision** → Random Forest model predicts approve/reject
5. **Explanation** → System generates human-readable reasons
6. **Notification** → Customer sees decision with next steps
7. **Documents** → If approved, upload Aadhaar/PAN/Salary for verification
8. **OCR Verification** → Textract extracts & cross-checks document data
9. **Final Approval** → System confirms or routes to manual review

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Customer portal |
| GET | `/health` | Health check |
| POST | `/api/auth/register` | Register user |
| POST | `/api/auth/login` | Login |
| POST | `/api/applications/submit` | Submit loan application |
| GET | `/api/applications/{id}/status` | Check application status |
| POST | `/api/applications/upload-document` | Upload verification document |
| POST | `/api/cibil/check` | Run CIBIL credit check |
| GET | `/api/dashboard/summary` | Analytics dashboard |

---

## Cost (Free Tier)

| Service | Monthly Cost |
|---------|-------------|
| Lambda | FREE (1M requests) |
| S3 | FREE (5GB) |
| DynamoDB | FREE (25 RCU/WCU) |
| Textract | FREE (1000 pages/3 months) |
| EC2 t2.micro | FREE (750 hrs/month for 12 months) |
| **Total** | **$0/month** (within free tier) |

---

## Switching CIBIL from Mock to Real

1. Register at https://www.cibil.com/business
2. Set environment variables:
```bash
export CIBIL_MODE=live
export CIBIL_API_URL=https://api.cibil.com
export CIBIL_API_KEY=your_key_here
```
3. Implement `_call_real_api()` in `services/cibil_service.py`

---

## Security Features

- JWT token authentication
- Input sanitization (prevent injection)
- Rate limiting (60 requests/minute)
- S3 encryption at rest
- Public access blocked
- IAM least-privilege roles
- PAN/Aadhaar format validation

---

## Cleanup

To remove all AWS resources:
```bash
chmod +x deploy/cleanup.sh
./deploy/cleanup.sh
```
