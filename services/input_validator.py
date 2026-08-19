"""
Input Validation Service
Validates all incoming loan application data before processing.
Prevents invalid data from reaching the ML model.
"""
import re
from datetime import datetime


class ValidationError:
    """Represents a validation error."""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def to_dict(self):
        return {"field": self.field, "message": self.message}


class LoanApplicationValidator:
    """
    Validates loan application form data.
    Returns clear error messages for invalid inputs.
    """

    # Valid options for categorical fields
    VALID_GENDERS = ["Male", "Female", "Other"]
    VALID_EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Self-employed", "Contract", "Freelance"]
    VALID_HOME_OWNERSHIP = ["OWN", "RENT", "MORTGAGE", "OTHER"]
    VALID_LOAN_INTENTS = ["PERSONAL", "EDUCATION", "MEDICAL", "HOME", "VEHICLE", "BUSINESS", "DEBTCONSOLIDATION"]
    VALID_ACCOUNT_TYPES = ["Checking", "Savings", "Both"]
    VALID_EDUCATION = ["High School", "Associate", "Bachelor", "Master", "Doctorate"]

    def validate_application(self, data: dict) -> tuple:
        """
        Validate a complete loan application.
        
        Args:
            data: Application form data
            
        Returns:
            (is_valid: bool, errors: list of ValidationError, sanitized_data: dict)
        """
        errors = []
        sanitized = {}

        # Required fields check
        required_fields = [
            "full_name", "person_age", "person_gender", "person_income",
            "person_emp_exp", "employment_type", "person_home_ownership",
            "loan_amnt", "loan_intent", "person_education",
            "pan_number", "aadhaar_number"
        ]

        for field in required_fields:
            if field not in data or data[field] is None or str(data[field]).strip() == "":
                errors.append(ValidationError(field, f"{field} is required"))

        if errors:
            return False, errors, None

        # Validate and sanitize each field
        sanitized["full_name"] = self._validate_name(data.get("full_name"), errors)
        sanitized["person_age"] = self._validate_age(data.get("person_age"), errors)
        sanitized["person_gender"] = self._validate_enum(
            data.get("person_gender"), "person_gender", self.VALID_GENDERS, errors
        )
        sanitized["person_income"] = self._validate_income(data.get("person_income"), errors)
        sanitized["person_emp_exp"] = self._validate_emp_exp(data.get("person_emp_exp"), errors)
        sanitized["employment_type"] = self._validate_enum(
            data.get("employment_type"), "employment_type", self.VALID_EMPLOYMENT_TYPES, errors
        )
        sanitized["person_home_ownership"] = self._validate_enum(
            data.get("person_home_ownership"), "person_home_ownership", self.VALID_HOME_OWNERSHIP, errors
        )
        sanitized["loan_amnt"] = self._validate_loan_amount(data.get("loan_amnt"), errors)
        sanitized["loan_intent"] = self._validate_enum(
            data.get("loan_intent"), "loan_intent", self.VALID_LOAN_INTENTS, errors
        )
        sanitized["loan_int_rate"] = self._validate_interest_rate(data.get("loan_int_rate", 0), errors)
        sanitized["person_education"] = self._validate_enum(
            data.get("person_education"), "person_education", self.VALID_EDUCATION, errors
        )
        sanitized["account_type"] = self._validate_enum(
            data.get("account_type", "Savings"), "account_type", self.VALID_ACCOUNT_TYPES, errors
        )
        sanitized["previous_loan_defaults_on_file"] = self._validate_yes_no(
            data.get("previous_loan_defaults_on_file", "No"), "previous_loan_defaults_on_file", errors
        )
        sanitized["cb_person_cred_hist_length"] = self._validate_credit_history(
            data.get("cb_person_cred_hist_length", 0), errors
        )
        sanitized["pan_number"] = self._validate_pan(data.get("pan_number"), errors)
        sanitized["aadhaar_number"] = self._validate_aadhaar(data.get("aadhaar_number"), errors)

        # Calculate derived fields
        if sanitized.get("loan_amnt") and sanitized.get("person_income"):
            sanitized["loan_percent_income"] = round(
                sanitized["loan_amnt"] / sanitized["person_income"], 4
            )
        else:
            sanitized["loan_percent_income"] = 0

        # Optional fields
        sanitized["email"] = self._validate_email(data.get("email", ""), errors)
        sanitized["phone"] = self._validate_phone(data.get("phone", ""), errors)
        sanitized["consent_cibil_check"] = data.get("consent_cibil_check", False)

        is_valid = len(errors) == 0
        return is_valid, errors, sanitized if is_valid else None

    def _validate_name(self, value, errors) -> str:
        if not value or len(str(value).strip()) < 2:
            errors.append(ValidationError("full_name", "Name must be at least 2 characters"))
            return ""
        name = str(value).strip()
        if len(name) > 100:
            errors.append(ValidationError("full_name", "Name must be less than 100 characters"))
            return ""
        if not re.match(r"^[A-Za-z\s.'-]+$", name):
            errors.append(ValidationError("full_name", "Name contains invalid characters"))
            return ""
        return name

    def _validate_age(self, value, errors) -> int:
        try:
            age = int(value)
            if age < 18:
                errors.append(ValidationError("person_age", "Applicant must be at least 18 years old"))
            elif age > 80:
                errors.append(ValidationError("person_age", "Applicant age exceeds maximum limit (80)"))
            return age
        except (ValueError, TypeError):
            errors.append(ValidationError("person_age", "Age must be a valid number"))
            return 0

    def _validate_income(self, value, errors) -> float:
        try:
            income = float(value)
            if income < 0:
                errors.append(ValidationError("person_income", "Income cannot be negative"))
            elif income > 100000000:  # 10 crore cap for sanity
                errors.append(ValidationError("person_income", "Income value seems unrealistic"))
            return income
        except (ValueError, TypeError):
            errors.append(ValidationError("person_income", "Income must be a valid number"))
            return 0

    def _validate_emp_exp(self, value, errors) -> int:
        try:
            exp = int(value)
            if exp < 0:
                errors.append(ValidationError("person_emp_exp", "Experience cannot be negative"))
            elif exp > 50:
                errors.append(ValidationError("person_emp_exp", "Experience value seems unrealistic"))
            return exp
        except (ValueError, TypeError):
            errors.append(ValidationError("person_emp_exp", "Experience must be a valid number"))
            return 0

    def _validate_loan_amount(self, value, errors) -> float:
        try:
            amount = float(value)
            if amount <= 0:
                errors.append(ValidationError("loan_amnt", "Loan amount must be greater than 0"))
            elif amount < 10000:
                errors.append(ValidationError("loan_amnt", "Minimum loan amount is ₹10,000"))
            elif amount > 50000000:  # 5 crore cap
                errors.append(ValidationError("loan_amnt", "Maximum loan amount is ₹5,00,00,000"))
            return amount
        except (ValueError, TypeError):
            errors.append(ValidationError("loan_amnt", "Loan amount must be a valid number"))
            return 0

    def _validate_interest_rate(self, value, errors) -> float:
        try:
            rate = float(value)
            if rate < 0:
                errors.append(ValidationError("loan_int_rate", "Interest rate cannot be negative"))
            elif rate > 40:
                errors.append(ValidationError("loan_int_rate", "Interest rate exceeds maximum (40%)"))
            return rate
        except (ValueError, TypeError):
            return 0.0

    def _validate_credit_history(self, value, errors) -> int:
        try:
            years = int(value)
            if years < 0:
                errors.append(ValidationError("cb_person_cred_hist_length", "Credit history cannot be negative"))
            elif years > 50:
                errors.append(ValidationError("cb_person_cred_hist_length", "Credit history value unrealistic"))
            return years
        except (ValueError, TypeError):
            return 0

    def _validate_enum(self, value, field_name, valid_options, errors) -> str:
        if not value:
            errors.append(ValidationError(field_name, f"{field_name} is required"))
            return ""
        value_str = str(value).strip()
        if value_str not in valid_options:
            errors.append(ValidationError(
                field_name,
                f"Invalid value '{value_str}'. Must be one of: {', '.join(valid_options)}"
            ))
            return ""
        return value_str

    def _validate_yes_no(self, value, field_name, errors) -> str:
        value_str = str(value).strip()
        if value_str not in ["Yes", "No"]:
            errors.append(ValidationError(field_name, "Must be 'Yes' or 'No'"))
            return "No"
        return value_str

    def _validate_pan(self, value, errors) -> str:
        if not value:
            errors.append(ValidationError("pan_number", "PAN number is required"))
            return ""
        pan = str(value).strip().upper()
        if not re.match(r"^[A-Z]{5}\d{4}[A-Z]$", pan):
            errors.append(ValidationError(
                "pan_number",
                "Invalid PAN format. Expected format: ABCDE1234F"
            ))
            return ""
        return pan

    def _validate_aadhaar(self, value, errors) -> str:
        if not value:
            errors.append(ValidationError("aadhaar_number", "Aadhaar number is required"))
            return ""
        aadhaar = str(value).strip().replace(" ", "")
        if not re.match(r"^\d{12}$", aadhaar):
            errors.append(ValidationError(
                "aadhaar_number",
                "Aadhaar must be exactly 12 digits"
            ))
            return ""
        return aadhaar

    def _validate_email(self, value, errors) -> str:
        if not value:
            return ""
        email = str(value).strip().lower()
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            errors.append(ValidationError("email", "Invalid email format"))
            return ""
        return email

    def _validate_phone(self, value, errors) -> str:
        if not value:
            return ""
        phone = str(value).strip().replace(" ", "").replace("-", "")
        if not re.match(r"^(\+91)?[6-9]\d{9}$", phone):
            errors.append(ValidationError(
                "phone",
                "Invalid Indian phone number. Expected 10 digits starting with 6-9"
            ))
            return ""
        return phone
