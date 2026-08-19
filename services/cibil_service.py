"""
CIBIL Credit Bureau Service
Mock implementation - pluggable for real CIBIL API integration later.

To switch to real CIBIL API:
1. Set CIBIL_MODE=live in environment
2. Set CIBIL_API_URL to actual endpoint
3. Set CIBIL_API_KEY with your credentials
"""
import random
import hashlib
from datetime import datetime, timedelta


class CIBILService:
    """
    Mock CIBIL credit bureau service.
    Generates realistic credit data based on PAN number.
    Replace with real API calls when CIBIL access is available.
    """

    def __init__(self, mode="mock", api_url=None, api_key=None):
        self.mode = mode
        self.api_url = api_url
        self.api_key = api_key

    def get_credit_report(self, pan_number: str, consent: bool = True) -> dict:
        """
        Fetch credit report for a given PAN number.
        
        Args:
            pan_number: Indian PAN card number (e.g., ABCDE1234F)
            consent: Customer consent for credit check (required by law)
            
        Returns:
            dict with credit score, history, active loans, etc.
        """
        if not consent:
            return {
                "status": "error",
                "message": "Customer consent required for credit check"
            }

        if not self._validate_pan(pan_number):
            return {
                "status": "error",
                "message": "Invalid PAN number format"
            }

        if self.mode == "live":
            return self._call_real_api(pan_number)
        else:
            return self._generate_mock_report(pan_number)

    def _validate_pan(self, pan: str) -> bool:
        """Validate Indian PAN format: ABCDE1234F"""
        if not pan or len(pan) != 10:
            return False
        # PAN format: 5 letters + 4 digits + 1 letter
        if not pan[:5].isalpha():
            return False
        if not pan[5:9].isdigit():
            return False
        if not pan[9].isalpha():
            return False
        return True

    def _generate_mock_report(self, pan_number: str) -> dict:
        """
        Generate deterministic mock credit report based on PAN.
        Same PAN always returns same score (for testing consistency).
        """
        # Use PAN hash for deterministic random values
        seed = int(hashlib.md5(pan_number.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Generate credit score (300-900, weighted toward middle)
        score = int(rng.gauss(700, 100))
        score = max(300, min(900, score))

        # Generate loan history based on score
        if score >= 750:
            active_loans = rng.randint(0, 2)
            defaults = 0
            late_payments = rng.randint(0, 2)
        elif score >= 650:
            active_loans = rng.randint(1, 3)
            defaults = rng.randint(0, 1)
            late_payments = rng.randint(2, 6)
        elif score >= 550:
            active_loans = rng.randint(1, 4)
            defaults = rng.randint(1, 2)
            late_payments = rng.randint(4, 10)
        else:
            active_loans = rng.randint(2, 5)
            defaults = rng.randint(2, 4)
            late_payments = rng.randint(8, 20)

        # Generate outstanding debt
        outstanding_debt = rng.randint(0, 500000) if active_loans > 0 else 0
        monthly_emi = int(outstanding_debt * 0.03) if outstanding_debt > 0 else 0

        # Generate enquiry count (last 6 months)
        recent_enquiries = rng.randint(0, 5)

        # Credit age
        credit_age_years = rng.randint(1, 20)

        return {
            "status": "success",
            "pan_number": pan_number,
            "report_date": datetime.now().isoformat(),
            "credit_score": {
                "score": score,
                "rating": self._get_rating(score),
                "score_range": {"min": 300, "max": 900}
            },
            "account_summary": {
                "active_loans": active_loans,
                "closed_loans": rng.randint(0, 5),
                "total_outstanding_debt": outstanding_debt,
                "monthly_emi_obligations": monthly_emi,
                "credit_utilization_percent": rng.randint(10, 90) if active_loans > 0 else 0
            },
            "payment_history": {
                "on_time_payments_percent": max(60, 100 - (late_payments * 3)),
                "late_payments_30_days": late_payments,
                "late_payments_60_days": max(0, late_payments - 3),
                "late_payments_90_days": max(0, late_payments - 6),
                "defaults": defaults,
                "settled_accounts": rng.randint(0, defaults)
            },
            "enquiry_history": {
                "last_6_months": recent_enquiries,
                "last_12_months": recent_enquiries + rng.randint(0, 3)
            },
            "credit_age": {
                "oldest_account_years": credit_age_years,
                "newest_account_months": rng.randint(1, 24)
            },
            "loan_types": self._generate_loan_types(rng, active_loans),
            "remarks": self._generate_remarks(score, defaults)
        }

    def _get_rating(self, score: int) -> str:
        if score >= 750:
            return "EXCELLENT"
        elif score >= 700:
            return "GOOD"
        elif score >= 650:
            return "FAIR"
        elif score >= 550:
            return "POOR"
        else:
            return "VERY_POOR"

    def _generate_loan_types(self, rng, active_loans: int) -> list:
        loan_types = ["Personal Loan", "Home Loan", "Auto Loan", "Credit Card", "Education Loan"]
        result = []
        for i in range(min(active_loans, len(loan_types))):
            result.append({
                "type": rng.choice(loan_types),
                "outstanding": rng.randint(10000, 500000),
                "emi": rng.randint(2000, 30000),
                "status": "Active"
            })
        return result

    def _generate_remarks(self, score: int, defaults: int) -> list:
        remarks = []
        if defaults > 0:
            remarks.append(f"{defaults} default(s) found in credit history")
        if score < 650:
            remarks.append("Credit score below recommended threshold")
        if score >= 750:
            remarks.append("Excellent credit history - low risk borrower")
        return remarks

    def _call_real_api(self, pan_number: str) -> dict:
        """
        Placeholder for real CIBIL API integration.
        
        To implement:
        1. Register at https://www.cibil.com/business
        2. Get API credentials
        3. Implement OAuth2 authentication
        4. Call TransUnion CIBIL Connect API
        
        Example endpoint: POST https://api.cibil.com/v1/credit-report
        Headers: Authorization: Bearer {token}
        Body: {"pan": pan_number, "consent": true}
        """
        # TODO: Replace with actual API call
        # import requests
        # headers = {
        #     "Authorization": f"Bearer {self.api_key}",
        #     "Content-Type": "application/json"
        # }
        # payload = {
        #     "pan_number": pan_number,
        #     "purpose": "loan_application",
        #     "consent": True,
        #     "consent_timestamp": datetime.now().isoformat()
        # }
        # response = requests.post(f"{self.api_url}/v1/credit-report", 
        #                          json=payload, headers=headers)
        # return response.json()
        
        raise NotImplementedError(
            "Real CIBIL API not configured. "
            "Set CIBIL_MODE=mock for testing or configure API credentials."
        )
