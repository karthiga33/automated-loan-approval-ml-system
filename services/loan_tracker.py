"""
Loan Repayment Tracker & EMI Monitoring Service
Tracks: EMI schedule, payments, bounces, penalties, outstanding balance.
Maps salary date to EMI date for cash flow tracking.
"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path


class LoanTracker:
    """
    Complete post-disbursement loan lifecycle management.
    Tracks EMI payments, bounces, penalties, and repayment health.
    """

    # Penalty rates (as per RBI guidelines)
    LATE_PAYMENT_PENALTY_PERCENT = 2.0  # 2% per month on overdue EMI
    BOUNCE_CHARGE = 500  # Fixed charge per bounce (₹500)
    GRACE_PERIOD_DAYS = 3  # Days after due date before penalty

    def __init__(self, data_dir="local_data"):
        self.data_dir = Path(data_dir)
        (self.data_dir / "loans").mkdir(parents=True, exist_ok=True)

    def create_loan_account(self, application_id: str, loan_data: dict) -> dict:
        """
        Create a loan account after disbursement.
        Generates full EMI schedule.
        """
        loan_amount = loan_data.get("loan_amount", 0)
        interest_rate = loan_data.get("interest_rate", 10.0)  # Annual %
        tenure_months = loan_data.get("tenure_months", 36)
        emi_date = loan_data.get("emi_date", 5)  # Day of month
        salary_date = loan_data.get("salary_date", 1)  # Day of month
        disbursement_date = loan_data.get("disbursement_date",
                                          datetime.now().strftime("%Y-%m-%d"))

        # Calculate EMI using standard formula
        monthly_rate = interest_rate / (12 * 100)
        if monthly_rate > 0:
            emi = loan_amount * monthly_rate * (
                (1 + monthly_rate) ** tenure_months
            ) / ((1 + monthly_rate) ** tenure_months - 1)
        else:
            emi = loan_amount / tenure_months

        emi = round(emi, 2)
        total_payable = round(emi * tenure_months, 2)
        total_interest = round(total_payable - loan_amount, 2)

        # Generate amortization schedule
        schedule = self._generate_schedule(
            loan_amount, monthly_rate, emi, tenure_months,
            emi_date, disbursement_date
        )

        loan_account = {
            "loan_id": f"LN-{application_id.split('-')[-1]}",
            "application_id": application_id,
            "status": "ACTIVE",
            "disbursement_date": disbursement_date,
            "loan_amount": loan_amount,
            "interest_rate": interest_rate,
            "tenure_months": tenure_months,
            "emi_amount": emi,
            "emi_date": emi_date,
            "salary_date": salary_date,
            "total_payable": total_payable,
            "total_interest": total_interest,
            "outstanding_principal": loan_amount,
            "emis_paid": 0,
            "emis_remaining": tenure_months,
            "total_paid": 0,
            "total_penalty": 0,
            "bounces": 0,
            "schedule": schedule,
            "payment_history": [],
            "customer_name": loan_data.get("customer_name", ""),
            "bank_account": loan_data.get("bank_account", ""),
            "created_at": datetime.now().isoformat()
        }

        # Save loan account
        loan_file = self.data_dir / "loans" / f"{loan_account['loan_id']}.json"
        with open(loan_file, "w") as f:
            json.dump(loan_account, f, indent=2)

        return loan_account

    def _generate_schedule(self, principal, monthly_rate, emi,
                           tenure, emi_day, start_date):
        """Generate month-by-month amortization schedule."""
        schedule = []
        balance = principal
        start = datetime.strptime(start_date, "%Y-%m-%d")

        for month in range(1, tenure + 1):
            interest_component = round(balance * monthly_rate, 2)
            principal_component = round(emi - interest_component, 2)
            balance = round(balance - principal_component, 2)
            if balance < 0:
                balance = 0

            # Calculate due date
            due_date = start + timedelta(days=30 * month)
            due_date = due_date.replace(day=min(emi_day, 28))

            schedule.append({
                "emi_number": month,
                "due_date": due_date.strftime("%Y-%m-%d"),
                "emi_amount": emi,
                "principal": principal_component,
                "interest": interest_component,
                "outstanding_after": balance,
                "status": "UPCOMING",  # PAID, LATE, BOUNCED, UPCOMING
                "paid_date": None,
                "penalty": 0,
                "remarks": ""
            })

        return schedule

    def record_payment(self, loan_id: str, emi_number: int,
                       payment_data: dict) -> dict:
        """
        Record an EMI payment (success, late, or bounce).
        """
        loan = self._load_loan(loan_id)
        if not loan:
            return {"error": "Loan not found"}

        if emi_number < 1 or emi_number > len(loan["schedule"]):
            return {"error": "Invalid EMI number"}

        emi_entry = loan["schedule"][emi_number - 1]
        payment_status = payment_data.get("status", "PAID")
        paid_date = payment_data.get("paid_date", datetime.now().strftime("%Y-%m-%d"))

        # Calculate penalty if applicable
        penalty = 0
        due_date = datetime.strptime(emi_entry["due_date"], "%Y-%m-%d")
        pay_date = datetime.strptime(paid_date, "%Y-%m-%d")

        if payment_status == "BOUNCED":
            penalty = self.BOUNCE_CHARGE
            emi_entry["status"] = "BOUNCED"
            emi_entry["remarks"] = "NACH/Auto-debit failed - Insufficient funds"
            loan["bounces"] += 1
        elif payment_status == "PAID":
            days_late = (pay_date - due_date).days - self.GRACE_PERIOD_DAYS
            if days_late > 0:
                # Late payment penalty
                penalty = round(
                    emi_entry["emi_amount"] * (self.LATE_PAYMENT_PENALTY_PERCENT / 100) *
                    (days_late / 30), 2
                )
                emi_entry["status"] = "LATE"
                emi_entry["remarks"] = f"Paid {days_late + self.GRACE_PERIOD_DAYS} days late"
            else:
                emi_entry["status"] = "PAID"
                emi_entry["remarks"] = "Paid on time"

            emi_entry["paid_date"] = paid_date
            loan["emis_paid"] += 1
            loan["emis_remaining"] -= 1
            loan["total_paid"] += emi_entry["emi_amount"]
            loan["outstanding_principal"] = emi_entry["outstanding_after"]

        emi_entry["penalty"] = penalty
        loan["total_penalty"] += penalty

        # Add to payment history
        loan["payment_history"].append({
            "emi_number": emi_number,
            "due_date": emi_entry["due_date"],
            "paid_date": paid_date,
            "amount": emi_entry["emi_amount"],
            "penalty": penalty,
            "status": emi_entry["status"],
            "remarks": emi_entry["remarks"],
            "recorded_at": datetime.now().isoformat()
        })

        # Check if loan is closed
        if loan["emis_remaining"] == 0:
            loan["status"] = "CLOSED"

        self._save_loan(loan)
        return {
            "status": "recorded",
            "emi_number": emi_number,
            "payment_status": emi_entry["status"],
            "penalty_applied": penalty,
            "outstanding_principal": loan["outstanding_principal"]
        }

    def get_loan_summary(self, loan_id: str) -> dict:
        """Get complete loan summary with health score."""
        loan = self._load_loan(loan_id)
        if not loan:
            return {"error": "Loan not found"}

        # Calculate repayment health score
        paid_emis = [s for s in loan["schedule"] if s["status"] in ["PAID", "LATE"]]
        on_time = sum(1 for s in paid_emis if s["status"] == "PAID")
        late = sum(1 for s in paid_emis if s["status"] == "LATE")
        bounced = sum(1 for s in loan["schedule"] if s["status"] == "BOUNCED")

        total_tracked = on_time + late + bounced
        health_score = round((on_time / total_tracked * 100)) if total_tracked > 0 else 100

        # Payment health rating
        if health_score >= 90:
            health_rating = "EXCELLENT"
            health_color = "#059669"
        elif health_score >= 75:
            health_rating = "GOOD"
            health_color = "#2563eb"
        elif health_score >= 50:
            health_rating = "FAIR"
            health_color = "#d97706"
        else:
            health_rating = "POOR"
            health_color = "#dc2626"

        # Next EMI info
        next_emi = None
        for s in loan["schedule"]:
            if s["status"] == "UPCOMING":
                next_emi = s
                break

        # Salary vs EMI flow
        salary_date = loan.get("salary_date", 1)
        emi_date = loan.get("emi_date", 5)
        days_between = emi_date - salary_date
        if days_between < 0:
            days_between += 30
        cash_flow_ok = days_between <= 10  # EMI within 10 days of salary

        return {
            "loan_id": loan["loan_id"],
            "application_id": loan["application_id"],
            "customer_name": loan.get("customer_name", ""),
            "status": loan["status"],
            "loan_amount": loan["loan_amount"],
            "interest_rate": loan["interest_rate"],
            "emi_amount": loan["emi_amount"],
            "tenure_months": loan["tenure_months"],
            "disbursement_date": loan["disbursement_date"],
            "summary": {
                "total_paid": loan["total_paid"],
                "outstanding_principal": loan["outstanding_principal"],
                "emis_paid": loan["emis_paid"],
                "emis_remaining": loan["emis_remaining"],
                "total_penalty": loan["total_penalty"],
                "total_bounces": loan["bounces"]
            },
            "health": {
                "score": health_score,
                "rating": health_rating,
                "color": health_color,
                "on_time_payments": on_time,
                "late_payments": late,
                "bounced_payments": bounced
            },
            "cash_flow": {
                "salary_date": salary_date,
                "emi_date": emi_date,
                "days_after_salary": days_between,
                "flow_status": "HEALTHY" if cash_flow_ok else "AT_RISK",
                "recommendation": (
                    f"EMI debits {days_between} days after salary credit - Good cash flow"
                    if cash_flow_ok else
                    f"EMI debits {days_between} days after salary - Consider changing EMI date closer to salary date"
                )
            },
            "next_emi": next_emi,
            "schedule": loan["schedule"],
            "payment_history": loan["payment_history"]
        }

    def get_all_loans(self) -> list:
        """Get all loan accounts."""
        loans = []
        loans_dir = self.data_dir / "loans"
        for f in loans_dir.glob("*.json"):
            try:
                with open(f) as file:
                    loan = json.load(file)
                    loans.append({
                        "loan_id": loan["loan_id"],
                        "customer_name": loan.get("customer_name", ""),
                        "loan_amount": loan["loan_amount"],
                        "emi_amount": loan["emi_amount"],
                        "status": loan["status"],
                        "emis_paid": loan["emis_paid"],
                        "emis_remaining": loan["emis_remaining"],
                        "bounces": loan["bounces"]
                    })
            except Exception:
                continue
        return loans

    def _load_loan(self, loan_id: str) -> dict:
        loan_file = self.data_dir / "loans" / f"{loan_id}.json"
        if not loan_file.exists():
            return None
        with open(loan_file) as f:
            return json.load(f)

    def _save_loan(self, loan: dict):
        loan_file = self.data_dir / "loans" / f"{loan['loan_id']}.json"
        with open(loan_file, "w") as f:
            json.dump(loan, f, indent=2)
