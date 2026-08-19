"""
Document Verification Service
Uses AWS Textract for OCR and validates extracted data against application form.
"""
import boto3
import json
import re
from datetime import datetime


class DocumentVerificationService:
    """
    Handles document upload processing, OCR extraction, and verification.
    Uses AWS Textract (free tier: 1000 pages/month for first 3 months).
    """

    def __init__(self, region="us-east-1", bucket_name="loan-approval-ml-system"):
        self.region = region
        self.bucket_name = bucket_name
        self.textract = boto3.client("textract", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)

    def process_document(self, application_id: str, document_type: str, s3_key: str) -> dict:
        """
        Process an uploaded document using AWS Textract OCR.
        
        Args:
            application_id: Unique application identifier
            document_type: One of 'aadhaar', 'pan', 'salary_slip', 'bank_statement'
            s3_key: S3 key where document is stored
            
        Returns:
            dict with extracted data and verification status
        """
        try:
            # Call Textract to extract text
            extracted_text = self._extract_text(s3_key)

            # Parse based on document type
            if document_type == "aadhaar":
                parsed_data = self._parse_aadhaar(extracted_text)
            elif document_type == "pan":
                parsed_data = self._parse_pan(extracted_text)
            elif document_type == "salary_slip":
                parsed_data = self._parse_salary_slip(extracted_text)
            elif document_type == "bank_statement":
                parsed_data = self._parse_bank_statement(extracted_text)
            else:
                return {
                    "status": "error",
                    "message": f"Unsupported document type: {document_type}"
                }

            return {
                "status": "success",
                "application_id": application_id,
                "document_type": document_type,
                "extracted_data": parsed_data,
                "extraction_timestamp": datetime.now().isoformat(),
                "s3_key": s3_key
            }

        except Exception as e:
            return {
                "status": "error",
                "application_id": application_id,
                "document_type": document_type,
                "message": str(e)
            }

    def _extract_text(self, s3_key: str) -> str:
        """Extract text from document using AWS Textract."""
        response = self.textract.detect_document_text(
            Document={
                "S3Object": {
                    "Bucket": self.bucket_name,
                    "Name": s3_key
                }
            }
        )

        # Combine all detected text blocks
        lines = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                lines.append(block["Text"])

        return "\n".join(lines)

    def _parse_aadhaar(self, text: str) -> dict:
        """Extract information from Aadhaar card text."""
        data = {
            "name": None,
            "dob": None,
            "gender": None,
            "aadhaar_number": None,
            "address": None
        }

        lines = text.split("\n")

        for line in lines:
            # Extract Aadhaar number (12 digits, may have spaces)
            aadhaar_match = re.search(r"\d{4}\s?\d{4}\s?\d{4}", line)
            if aadhaar_match:
                data["aadhaar_number"] = aadhaar_match.group().replace(" ", "")

            # Extract DOB
            dob_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
            if dob_match:
                data["dob"] = dob_match.group()

            # Extract gender
            if "male" in line.lower() and "female" not in line.lower():
                data["gender"] = "Male"
            elif "female" in line.lower():
                data["gender"] = "Female"

        # Name is typically the first meaningful line after header
        for line in lines:
            if (len(line) > 3 and line.isalpha() is False and
                    "government" not in line.lower() and
                    "india" not in line.lower() and
                    "aadhaar" not in line.lower()):
                if not data["name"] and len(line.strip()) > 2:
                    # Simple heuristic: first line that looks like a name
                    if re.match(r"^[A-Za-z\s]+$", line.strip()):
                        data["name"] = line.strip()

        return data

    def _parse_pan(self, text: str) -> dict:
        """Extract information from PAN card text."""
        data = {
            "name": None,
            "father_name": None,
            "dob": None,
            "pan_number": None
        }

        lines = text.split("\n")

        for line in lines:
            # Extract PAN number (format: ABCDE1234F)
            pan_match = re.search(r"[A-Z]{5}\d{4}[A-Z]", line)
            if pan_match:
                data["pan_number"] = pan_match.group()

            # Extract DOB
            dob_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
            if dob_match:
                data["dob"] = dob_match.group()

        return data

    def _parse_salary_slip(self, text: str) -> dict:
        """Extract salary information from salary slip."""
        data = {
            "employee_name": None,
            "employer_name": None,
            "month": None,
            "gross_salary": None,
            "net_salary": None,
            "basic_salary": None,
            "deductions": None
        }

        lines = text.split("\n")

        for line in lines:
            lower_line = line.lower()

            # Extract amounts
            amount_match = re.search(r"[\d,]+\.?\d*", line)

            if "gross" in lower_line and amount_match:
                data["gross_salary"] = self._parse_amount(amount_match.group())
            elif "net" in lower_line and amount_match:
                data["net_salary"] = self._parse_amount(amount_match.group())
            elif "basic" in lower_line and amount_match:
                data["basic_salary"] = self._parse_amount(amount_match.group())
            elif "deduction" in lower_line and amount_match:
                data["deductions"] = self._parse_amount(amount_match.group())

        return data

    def _parse_bank_statement(self, text: str) -> dict:
        """Extract key information from bank statement."""
        data = {
            "account_holder": None,
            "account_number": None,
            "bank_name": None,
            "statement_period": None,
            "total_credits": 0,
            "total_debits": 0,
            "average_balance": 0,
            "salary_credits": [],
            "monthly_summary": []
        }

        lines = text.split("\n")
        credits = []
        debits = []

        for line in lines:
            # Look for credit/debit amounts
            amount_match = re.findall(r"[\d,]+\.?\d*", line)
            lower_line = line.lower()

            if "salary" in lower_line or "sal" in lower_line:
                for amt in amount_match:
                    parsed = self._parse_amount(amt)
                    if parsed > 10000:  # Reasonable salary threshold
                        data["salary_credits"].append(parsed)

            # Account number
            acc_match = re.search(r"\d{10,18}", line)
            if acc_match and not data["account_number"]:
                data["account_number"] = acc_match.group()

        if data["salary_credits"]:
            data["average_monthly_salary"] = sum(data["salary_credits"]) / len(data["salary_credits"])

        return data

    def _parse_amount(self, amount_str: str) -> float:
        """Parse amount string to float."""
        try:
            return float(amount_str.replace(",", ""))
        except (ValueError, AttributeError):
            return 0.0

    def verify_against_application(self, application_data: dict, extracted_docs: dict) -> dict:
        """
        Cross-verify extracted document data against application form data.
        
        Args:
            application_data: Data from the application form
            extracted_docs: Data extracted from uploaded documents
            
        Returns:
            Verification result with match scores
        """
        verification = {
            "overall_status": "pending",
            "checks": [],
            "match_score": 0,
            "flags": []
        }

        total_checks = 0
        passed_checks = 0

        # 1. Name verification (Aadhaar vs Form)
        if "aadhaar" in extracted_docs:
            aadhaar_name = extracted_docs["aadhaar"].get("name", "")
            form_name = application_data.get("full_name", "")
            if aadhaar_name and form_name:
                total_checks += 1
                name_match = self._fuzzy_name_match(aadhaar_name, form_name)
                if name_match > 0.8:
                    passed_checks += 1
                    verification["checks"].append({
                        "check": "name_match",
                        "status": "passed",
                        "confidence": name_match
                    })
                else:
                    verification["flags"].append("Name mismatch between form and Aadhaar")
                    verification["checks"].append({
                        "check": "name_match",
                        "status": "failed",
                        "confidence": name_match
                    })

        # 2. Income verification (Salary slip vs Form)
        if "salary_slip" in extracted_docs:
            doc_salary = extracted_docs["salary_slip"].get("net_salary") or \
                         extracted_docs["salary_slip"].get("gross_salary", 0)
            form_income = application_data.get("person_income", 0)
            monthly_form_income = form_income / 12 if form_income > 0 else 0

            if doc_salary and monthly_form_income:
                total_checks += 1
                # Allow 20% variance
                income_ratio = min(doc_salary, monthly_form_income) / max(doc_salary, monthly_form_income) if max(doc_salary, monthly_form_income) > 0 else 0
                if income_ratio > 0.8:
                    passed_checks += 1
                    verification["checks"].append({
                        "check": "income_match",
                        "status": "passed",
                        "confidence": income_ratio
                    })
                else:
                    verification["flags"].append(
                        f"Income mismatch: Form says {form_income}/year, "
                        f"salary slip shows {doc_salary}/month"
                    )
                    verification["checks"].append({
                        "check": "income_match",
                        "status": "failed",
                        "confidence": income_ratio
                    })

        # 3. PAN verification
        if "pan" in extracted_docs:
            pan_number = extracted_docs["pan"].get("pan_number", "")
            form_pan = application_data.get("pan_number", "")
            if pan_number and form_pan:
                total_checks += 1
                if pan_number.upper() == form_pan.upper():
                    passed_checks += 1
                    verification["checks"].append({
                        "check": "pan_match",
                        "status": "passed",
                        "confidence": 1.0
                    })
                else:
                    verification["flags"].append("PAN number mismatch")
                    verification["checks"].append({
                        "check": "pan_match",
                        "status": "failed",
                        "confidence": 0.0
                    })

        # Calculate overall score
        if total_checks > 0:
            verification["match_score"] = round(passed_checks / total_checks, 2)
            if verification["match_score"] >= 0.8:
                verification["overall_status"] = "verified"
            elif verification["match_score"] >= 0.5:
                verification["overall_status"] = "partial_verification"
            else:
                verification["overall_status"] = "verification_failed"
        else:
            verification["overall_status"] = "no_documents_processed"

        return verification

    def _fuzzy_name_match(self, name1: str, name2: str) -> float:
        """Simple fuzzy name matching."""
        if not name1 or not name2:
            return 0.0

        # Normalize
        n1 = name1.lower().strip().split()
        n2 = name2.lower().strip().split()

        # Check how many name parts match
        matches = sum(1 for part in n1 if part in n2)
        total = max(len(n1), len(n2))

        return matches / total if total > 0 else 0.0
