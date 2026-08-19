#!/bin/bash
# ============================================================
# Loan Approval System - Test Script
# Run this in CloudShell or locally after deployment
# ============================================================

echo "=========================================="
echo " LOAN APPROVAL SYSTEM - TESTING"
echo "=========================================="

API_URL="${1:-http://localhost:8000}"
echo " API URL: ${API_URL}"
echo ""

# Test 1: Health Check
echo "[Test 1] Health Check..."
echo "-------------------------------------------"
curl -s ${API_URL}/health | python3 -m json.tool
echo ""

# Test 2: Submit Application (Good applicant - should be APPROVED)
echo "[Test 2] Submit Application - Good Applicant..."
echo "-------------------------------------------"
curl -s -X POST ${API_URL}/api/applications/submit \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Rajesh Kumar",
    "person_age": 35,
    "person_gender": "Male",
    "person_income": 800000,
    "person_emp_exp": 8,
    "employment_type": "Full-time",
    "person_home_ownership": "OWN",
    "loan_amnt": 200000,
    "loan_intent": "PERSONAL",
    "loan_int_rate": 8.5,
    "cb_person_cred_hist_length": 10,
    "person_education": "Bachelor",
    "account_type": "Savings",
    "previous_loan_defaults_on_file": "No",
    "pan_number": "ABCDE1234F",
    "aadhaar_number": "123456789012",
    "email": "rajesh@example.com",
    "phone": "9876543210",
    "consent_cibil_check": true
  }' | python3 -m json.tool
echo ""

# Test 3: Submit Application (Risky applicant - should be REJECTED)
echo "[Test 3] Submit Application - Risky Applicant..."
echo "-------------------------------------------"
curl -s -X POST ${API_URL}/api/applications/submit \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Test User",
    "person_age": 22,
    "person_gender": "Male",
    "person_income": 200000,
    "person_emp_exp": 1,
    "employment_type": "Part-time",
    "person_home_ownership": "RENT",
    "loan_amnt": 500000,
    "loan_intent": "PERSONAL",
    "loan_int_rate": 15.0,
    "cb_person_cred_hist_length": 1,
    "person_education": "High School",
    "account_type": "Savings",
    "previous_loan_defaults_on_file": "Yes",
    "pan_number": "ZZZZZ9999Z",
    "aadhaar_number": "999999999999",
    "email": "test@example.com",
    "phone": "9000000000",
    "consent_cibil_check": true
  }' | python3 -m json.tool
echo ""

# Test 4: Invalid Application (should get validation errors)
echo "[Test 4] Submit Invalid Application..."
echo "-------------------------------------------"
curl -s -X POST ${API_URL}/api/applications/submit \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "",
    "person_age": 15,
    "person_income": -5000,
    "pan_number": "INVALID"
  }' | python3 -m json.tool
echo ""

# Test 5: CIBIL Check
echo "[Test 5] CIBIL Credit Check (Mock)..."
echo "-------------------------------------------"
curl -s -X POST ${API_URL}/api/cibil/check \
  -H "Content-Type: application/json" \
  -d '{
    "pan_number": "ABCDE1234F",
    "consent": true
  }' | python3 -m json.tool
echo ""

# Test 6: Dashboard Summary
echo "[Test 6] Dashboard Summary..."
echo "-------------------------------------------"
curl -s ${API_URL}/api/dashboard/summary | python3 -m json.tool
echo ""

echo "=========================================="
echo " ALL TESTS COMPLETE"
echo "=========================================="
echo ""
echo " Results:"
echo "   Test 1: Health check should show 'healthy'"
echo "   Test 2: Good applicant should be APPROVED"
echo "   Test 3: Risky applicant should be REJECTED"
echo "   Test 4: Invalid data should show validation errors"
echo "   Test 5: CIBIL check should return credit report"
echo "   Test 6: Dashboard should show statistics"
echo ""
echo " Open in browser: ${API_URL}/"
echo "=========================================="
