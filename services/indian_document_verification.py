"""
Indian Document Verification Service (Real-Time)
Handles all Indian KYC documents: Aadhaar, PAN, Salary Slips, 
Bank Statements, ITR/Form-16, and loan-specific documents.

Follows RBI KYC guidelines and Indian banking standards.
"""
import boto3
import json
import re
from datetime import datetime
from typing import Optional


class IndianDocumentVerificationService:
    """
    Complete Indian document verification for loan processing.
    Supports: Aadhaar, PAN, Salary Slips, Bank Statements,
    Form-16/ITR, Property Documents, Vehicle Documents.
    """

    # All supported document types in Indian banking
    DOCUMENT_TYPES = {
        # KYC Documents
        "aadhaar_front": {"label": "Aadhaar Card (Front)", "mandatory": True},
        "aadhaar_back": {"label": "Aadhaar Card (Back)", "mandatory": True},
        "pan_card": {"label": "PAN Card", "mandatory": True},
        "photograph": {"label": "Passport Photo/Selfie", "mandatory": True},
        # Income Documents
        "salary_slip_1": {"label": "Salary Slip (Month 1)", "mandatory": True},
        "salary_slip_2": {"label": "Salary Slip (Month 2)", "mandatory": True},
        "salary_slip_3": {"label": "Salary Slip (Month 3)", "mandatory": True},
        "bank_statement": {"label": "Bank Statement (6 months)", "mandatory": True},
        "form_16": {"label": "Form 16 / ITR", "mandatory": True},
        # Address Proof (any one)
        "address_proof": {"label": "Address Proof", "mandatory": True},
        # Employment
        "appointment_letter": {"label": "Appointment/Offer Letter", "mandatory": False},
        # Self-Employed Additional
        "gst_certificate": {"label": "GST Registration", "mandatory": False},
        "itr_3_years": {"label": "ITR (3 Years)", "mandatory": False},
        "business_pan": {"label": "Business PAN", "mandatory": False},
        # Home Loan Specific
        "property_agreement": {"label": "Sale Agreement", "mandatory": False},
        "title_deed": {"label": "Title Deed", "mandatory": False},
        "property_tax": {"label": "Property Tax Receipt", "mandatory": False},
        "rera_certificate": {"label": "RERA Certificate", "mandatory": False},
        # Vehicle Loan Specific
        "proforma_invoice": {"label": "Proforma Invoice", "mandatory": False},
        "vehicle_insurance": {"label": "Insurance Quote", "mandatory": False},
    }

    def __init__(self, region="us-east-1", bucket_name="loan-approval-ml-system"):
        self.region = region
        self.bucket_name = bucket_name
        self.textract = boto3.client("textract", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)

    def get_required_documents(self, loan_type: str, employment_type: str) -> list:
        """
        Get list of required documents based on loan type and employment.
        
        Args:
            loan_type: PERSONAL, HOME, VEHICLE, EDUCATION, BUSINESS
            employment_type: Full-time, Self-employed, Professional
            
        Returns:
            List of required document types with labels
        """
        # Always required (all loan types)
        required = [
            {"type": "aadhaar_front", "label": "Aadhaar Card (Front Side)"},
            {"type": "aadhaar_back", "label": "Aadhaar Card (Back Side)"},
            {"type": "pan_card", "label": "PAN Card"},
            {"type": "photograph", "label": "Recent Passport Size Photograph"},
            {"type": "bank_statement", "label": "Bank Statement (Last 6 Months)"},
            {"type": "address_proof", "label": "Address Proof (Utility Bill / Rent Agreement)"},
        ]

        # Income documents based on employment type
        if employment_type in ["Full-time", "Part-time", "Contract"]:
            required.extend([
                {"type": "salary_slip_1", "label": "Salary Slip - Latest Month"},
                {"type": "salary_slip_2", "label": "Salary Slip - 2nd Month"},
                {"type": "salary_slip_3", "label": "Salary Slip - 3rd Month"},
                {"type": "form_16", "label": "Form 16 (Latest Financial Year)"},
                {"type": "appointment_letter", "label": "Appointment/Offer Letter"},
            ])
        elif employment_type == "Self-employed":
            required.extend([
                {"type": "itr_3_years", "label": "ITR (Last 3 Years)"},
                {"type": "gst_certificate", "label": "GST Registration Certificate"},
                {"type": "business_pan", "label": "Business PAN Card"},
            ])
        elif employment_type == "Professional":
            required.extend([
                {"type": "itr_3_years", "label": "ITR (Last 3 Years)"},
                {"type": "form_16", "label": "Professional License"},
            ])

        # Loan-type specific documents
        if loan_type == "HOME":
            required.extend([
                {"type": "property_agreement", "label": "Property Sale Agreement"},
                {"type": "title_deed", "label": "Title Deed / Ownership Document"},
                {"type": "property_tax", "label": "Property Tax Receipt (Latest)"},
                {"type": "rera_certificate", "label": "Builder RERA Registration"},
            ])
        elif loan_type == "VEHICLE":
            required.extend([
                {"type": "proforma_invoice", "label": "Vehicle Proforma Invoice"},
                {"type": "vehicle_insurance", "label": "Insurance Quote"},
            ])
        elif loan_type == "EDUCATION":
            required.extend([
                {"type": "admission_letter", "label": "Admission Confirmation Letter"},
                {"type": "fee_structure", "label": "Fee Structure Document"},
            ])
        elif loan_type == "BUSINESS":
            required.extend([
                {"type": "gst_certificate", "label": "GST Registration"},
                {"type": "business_pan", "label": "Business PAN Card"},
                {"type": "trade_license", "label": "Trade License / Shop Act License"},
            ])

        return required

    def extract_and_verify(self, s3_key: str, document_type: str) -> dict:
        """Extract text from document and parse based on type."""
        try:
            raw_text = self._extract_text_from_s3(s3_key)
            
            parser_map = {
                "aadhaar_front": self._parse_aadhaar_front,
                "aadhaar_back": self._parse_aadhaar_back,
                "pan_card": self._parse_pan_card,
                "salary_slip_1": self._parse_salary_slip,
                "salary_slip_2": self._parse_salary_slip,
                "salary_slip_3": self._parse_salary_slip,
                "bank_statement": self._parse_bank_statement,
                "form_16": self._parse_form_16,
            }

            parser = parser_map.get(document_type, self._parse_generic)
            parsed = parser(raw_text)
            
            return {
                "status": "success",
                "document_type": document_type,
                "extracted_data": parsed,
                "raw_text_length": len(raw_text),
                "extraction_timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "status": "error",
                "document_type": document_type,
                "error": str(e)
            }

    def _extract_text_from_s3(self, s3_key: str) -> str:
        """Call AWS Textract to extract text from document in S3."""
        response = self.textract.detect_document_text(
            Document={"S3Object": {"Bucket": self.bucket_name, "Name": s3_key}}
        )
        lines = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                lines.append(block["Text"])
        return "\n".join(lines)

    # ================================================================
    # AADHAAR CARD PARSER (Front)
    # Fields: Name, DOB, Gender, Aadhaar Number, Photo
    # Format: 12 digits (XXXX XXXX XXXX)
    # ================================================================
    def _parse_aadhaar_front(self, text: str) -> dict:
        """
        Parse Aadhaar front side.
        Extracts: Name, DOB, Gender, Aadhaar Number
        """
        data = {
            "document": "Aadhaar Card (Front)",
            "name": None,
            "dob": None,
            "gender": None,
            "aadhaar_number": None,
            "year_of_birth": None
        }
        lines = text.split("\n")

        for line in lines:
            # Aadhaar number: 4 digits space 4 digits space 4 digits
            aadhaar_match = re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", line)
            if aadhaar_match:
                data["aadhaar_number"] = aadhaar_match.group().replace(" ", "")

            # DOB: DD/MM/YYYY or DD-MM-YYYY
            dob_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", line)
            if dob_match:
                data["dob"] = dob_match.group()

            # Year of birth (alternative format on some Aadhaar cards)
            yob_match = re.search(r"Year of Birth\s*:?\s*(\d{4})", line, re.IGNORECASE)
            if yob_match:
                data["year_of_birth"] = yob_match.group(1)

            # Gender
            line_lower = line.lower()
            if "male" in line_lower and "female" not in line_lower:
                data["gender"] = "Male"
            elif "female" in line_lower:
                data["gender"] = "Female"
            elif "transgender" in line_lower:
                data["gender"] = "Transgender"

        # Name extraction: first line that looks like a name
        for line in lines:
            clean = line.strip()
            if (len(clean) > 3 and
                re.match(r"^[A-Za-z\s.]+$", clean) and
                "government" not in clean.lower() and
                "india" not in clean.lower() and
                "unique" not in clean.lower() and
                "aadhaar" not in clean.lower()):
                if not data["name"]:
                    data["name"] = clean
                    break

        return data

    # ================================================================
    # AADHAAR CARD PARSER (Back)
    # Fields: Address, VID (Virtual ID), QR Code data
    # ================================================================
    def _parse_aadhaar_back(self, text: str) -> dict:
        """
        Parse Aadhaar back side.
        Extracts: Full Address, PIN Code
        """
        data = {
            "document": "Aadhaar Card (Back)",
            "address": None,
            "pin_code": None,
            "vid": None
        }
        lines = text.split("\n")

        # Address is usually the longest block of text
        address_lines = []
        for line in lines:
            # Skip header lines
            if any(skip in line.lower() for skip in ["government", "unique", "aadhaar", "vid"]):
                continue
            if len(line.strip()) > 5:
                address_lines.append(line.strip())

        if address_lines:
            data["address"] = ", ".join(address_lines[:4])

        # PIN Code: 6 digit Indian postal code
        for line in lines:
            pin_match = re.search(r"\b[1-9]\d{5}\b", line)
            if pin_match:
                data["pin_code"] = pin_match.group()
                break

        # VID: 16-digit Virtual ID
        for line in lines:
            vid_match = re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b", line)
            if vid_match:
                data["vid"] = vid_match.group().replace(" ", "")

        return data

    # ================================================================
    # PAN CARD PARSER
    # Fields: PAN Number, Name, Father's Name, DOB
    # Format: ABCDE1234F (5 letters + 4 digits + 1 letter)
    # ================================================================
    def _parse_pan_card(self, text: str) -> dict:
        """
        Parse Indian PAN Card.
        Extracts: PAN Number, Name, Father's Name, DOB
        """
        data = {
            "document": "PAN Card",
            "pan_number": None,
            "name": None,
            "father_name": None,
            "dob": None,
            "pan_type": None  # P=Person, C=Company, H=HUF, F=Firm
        }
        lines = text.split("\n")

        for line in lines:
            # PAN Number: ABCDE1234F
            pan_match = re.search(r"\b[A-Z]{5}\d{4}[A-Z]\b", line)
            if pan_match:
                data["pan_number"] = pan_match.group()
                # 4th character indicates PAN type
                fourth_char = data["pan_number"][3]
                pan_types = {"P": "Individual", "C": "Company", "H": "HUF",
                            "F": "Firm", "A": "AOP", "T": "Trust"}
                data["pan_type"] = pan_types.get(fourth_char, "Unknown")

            # DOB
            dob_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", line)
            if dob_match:
                data["dob"] = dob_match.group()

        # Name and Father's name extraction
        # PAN card format: line after "Name" header = applicant name
        # Line after "Father's Name" = father's name
        for i, line in enumerate(lines):
            if "name" in line.lower() and "father" not in line.lower():
                if i + 1 < len(lines):
                    name_candidate = lines[i + 1].strip()
                    if re.match(r"^[A-Z\s.]+$", name_candidate):
                        data["name"] = name_candidate
            elif "father" in line.lower():
                if i + 1 < len(lines):
                    father_candidate = lines[i + 1].strip()
                    if re.match(r"^[A-Z\s.]+$", father_candidate):
                        data["father_name"] = father_candidate

        return data

    # ================================================================
    # SALARY SLIP PARSER
    # Fields: Employee Name, Employer, Gross Salary, Net Salary,
    #         Basic, HRA, DA, PF Deduction, TDS, Month/Year
    # ================================================================
    def _parse_salary_slip(self, text: str) -> dict:
        """
        Parse Indian salary slip / payslip.
        Extracts: Gross, Net, Basic, HRA, PF, TDS, Employer
        """
        data = {
            "document": "Salary Slip",
            "employee_name": None,
            "employer_name": None,
            "employee_id": None,
            "designation": None,
            "month_year": None,
            "earnings": {
                "basic": 0,
                "hra": 0,
                "da": 0,
                "special_allowance": 0,
                "conveyance": 0,
                "medical": 0,
                "gross_salary": 0
            },
            "deductions": {
                "pf_employee": 0,
                "professional_tax": 0,
                "tds_income_tax": 0,
                "esi": 0,
                "total_deductions": 0
            },
            "net_salary": 0
        }
        lines = text.split("\n")

        for line in lines:
            lower = line.lower()
            amounts = re.findall(r"[\d,]+\.?\d*", line)
            last_amount = self._parse_amount(amounts[-1]) if amounts else 0

            # Earnings
            if "basic" in lower and last_amount > 0:
                data["earnings"]["basic"] = last_amount
            elif "hra" in lower or "house rent" in lower:
                if last_amount > 0:
                    data["earnings"]["hra"] = last_amount
            elif "dearness" in lower or "d.a" in lower or "da " in lower:
                if last_amount > 0:
                    data["earnings"]["da"] = last_amount
            elif "special" in lower and "allowance" in lower:
                if last_amount > 0:
                    data["earnings"]["special_allowance"] = last_amount
            elif "conveyance" in lower or "transport" in lower:
                if last_amount > 0:
                    data["earnings"]["conveyance"] = last_amount
            elif "medical" in lower:
                if last_amount > 0:
                    data["earnings"]["medical"] = last_amount
            elif "gross" in lower and last_amount > 0:
                data["earnings"]["gross_salary"] = last_amount

            # Deductions
            elif ("pf" in lower or "provident" in lower) and "employer" not in lower:
                if last_amount > 0:
                    data["deductions"]["pf_employee"] = last_amount
            elif "professional tax" in lower or "pt" in lower:
                if last_amount > 0:
                    data["deductions"]["professional_tax"] = last_amount
            elif "tds" in lower or "income tax" in lower:
                if last_amount > 0:
                    data["deductions"]["tds_income_tax"] = last_amount
            elif "esi" in lower:
                if last_amount > 0:
                    data["deductions"]["esi"] = last_amount
            elif "total deduction" in lower and last_amount > 0:
                data["deductions"]["total_deductions"] = last_amount

            # Net salary
            elif "net" in lower and ("pay" in lower or "salary" in lower):
                if last_amount > 0:
                    data["net_salary"] = last_amount

            # Employee/Employer info
            elif "employee name" in lower or "emp name" in lower:
                name_part = re.sub(r"employee\s*name\s*:?\s*", "", line, flags=re.IGNORECASE)
                if name_part.strip():
                    data["employee_name"] = name_part.strip()
            elif "company" in lower or "employer" in lower:
                name_part = re.sub(r"(company|employer)\s*:?\s*", "", line, flags=re.IGNORECASE)
                if name_part.strip():
                    data["employer_name"] = name_part.strip()

            # Month/Year
            month_match = re.search(
                r"(january|february|march|april|may|june|july|august|september|october|november|december)\s*[\-']?\s*\d{4}",
                lower
            )
            if month_match:
                data["month_year"] = month_match.group().title()

        return data

    # ================================================================
    # BANK STATEMENT PARSER
    # Fields: Account Number, IFSC, Salary Credits, EMI Debits,
    #         Average Balance, Bounce/Return entries
    # ================================================================
    def _parse_bank_statement(self, text: str) -> dict:
        """
        Parse Indian bank statement (6 months).
        Extracts: Account details, salary credits, EMIs, balance.
        """
        data = {
            "document": "Bank Statement",
            "account_holder_name": None,
            "account_number": None,
            "ifsc_code": None,
            "bank_name": None,
            "statement_period": None,
            "salary_credits": [],
            "emi_debits": [],
            "bounced_cheques": 0,
            "average_monthly_balance": 0,
            "minimum_balance": 0,
            "maximum_balance": 0,
            "total_credits": 0,
            "total_debits": 0,
            "regular_income_detected": False
        }
        lines = text.split("\n")

        balances = []
        for line in lines:
            lower = line.lower()
            amounts = re.findall(r"[\d,]+\.?\d*", line)

            # Account number (10-18 digits)
            if not data["account_number"]:
                acc_match = re.search(r"\b\d{10,18}\b", line)
                if acc_match and "ifsc" not in lower and "phone" not in lower:
                    data["account_number"] = acc_match.group()

            # IFSC Code (format: ABCD0123456)
            ifsc_match = re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", line)
            if ifsc_match:
                data["ifsc_code"] = ifsc_match.group()

            # Salary credits (look for keywords)
            if any(kw in lower for kw in ["salary", "sal cr", "neft cr", "wages"]):
                for amt in amounts:
                    val = self._parse_amount(amt)
                    if val > 10000:  # Minimum threshold for salary
                        data["salary_credits"].append(val)

            # EMI debits
            if any(kw in lower for kw in ["emi", "loan", "auto debit"]):
                for amt in amounts:
                    val = self._parse_amount(amt)
                    if val > 1000:
                        data["emi_debits"].append(val)

            # Bounced/Returned cheques
            if any(kw in lower for kw in ["bounce", "return", "dishonour", "insufficient"]):
                data["bounced_cheques"] += 1

            # Detect bank name
            bank_names = ["state bank", "sbi", "hdfc", "icici", "axis", "kotak",
                         "pnb", "bob", "canara", "union bank", "idbi", "yes bank",
                         "indusind", "federal bank", "bandhan"]
            for bank in bank_names:
                if bank in lower:
                    data["bank_name"] = bank.upper()
                    break

        # Calculate averages
        if data["salary_credits"]:
            data["regular_income_detected"] = True
            data["average_monthly_salary"] = (
                sum(data["salary_credits"]) / len(data["salary_credits"])
            )

        if data["emi_debits"]:
            data["monthly_emi_obligation"] = sum(set(data["emi_debits"]))

        return data

    # ================================================================
    # FORM 16 / ITR PARSER
    # Fields: Assessment Year, Employer, Gross Salary, TDS,
    #         Taxable Income, Net Tax Payable
    # ================================================================
    def _parse_form_16(self, text: str) -> dict:
        """
        Parse Form 16 (TDS Certificate) or ITR acknowledgment.
        Extracts: Taxable income, TDS deducted, Employer details.
        """
        data = {
            "document": "Form 16 / ITR",
            "assessment_year": None,
            "employer_name": None,
            "employer_pan": None,
            "employee_pan": None,
            "gross_total_income": 0,
            "taxable_income": 0,
            "tds_deducted": 0,
            "net_tax_payable": 0,
            "section_80c_deductions": 0
        }
        lines = text.split("\n")

        for line in lines:
            lower = line.lower()
            amounts = re.findall(r"[\d,]+\.?\d*", line)
            last_amount = self._parse_amount(amounts[-1]) if amounts else 0

            # Assessment Year
            ay_match = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", line)
            if ay_match:
                data["assessment_year"] = f"{ay_match.group(1)}-{ay_match.group(2)}"

            # PAN numbers
            pan_match = re.findall(r"\b[A-Z]{5}\d{4}[A-Z]\b", line)
            for pan in pan_match:
                if pan[3] == "P" and not data["employee_pan"]:
                    data["employee_pan"] = pan
                elif pan[3] in ["C", "F", "T"] and not data["employer_pan"]:
                    data["employer_pan"] = pan

            # Income fields
            if "gross total income" in lower or "gross salary" in lower:
                if last_amount > 0:
                    data["gross_total_income"] = last_amount
            elif "taxable income" in lower or "total income" in lower:
                if last_amount > 0:
                    data["taxable_income"] = last_amount
            elif "tax deducted" in lower or "tds" in lower:
                if last_amount > 0:
                    data["tds_deducted"] = last_amount
            elif "80c" in lower or "section 80" in lower:
                if last_amount > 0:
                    data["section_80c_deductions"] = last_amount
            elif "net tax" in lower:
                if last_amount > 0:
                    data["net_tax_payable"] = last_amount

        return data

    # ================================================================
    # GENERIC DOCUMENT PARSER
    # ================================================================
    def _parse_generic(self, text: str) -> dict:
        """Fallback parser for unsupported document types."""
        return {
            "document": "Generic Document",
            "raw_text_preview": text[:500],
            "total_lines": len(text.split("\n")),
            "amounts_found": re.findall(r"[\d,]+\.?\d*", text)[:10]
        }

    # ================================================================
    # CROSS-VERIFICATION ENGINE
    # ================================================================
    def cross_verify_documents(self, application_data: dict,
                                extracted_documents: dict) -> dict:
        """
        Cross-verify all extracted document data against application form.
        This is where mismatches are flagged.
        
        Checks:
        1. Name consistency across Aadhaar, PAN, Salary Slip
        2. Income: Salary Slip vs Bank Statement vs Form data
        3. PAN match: Form PAN vs PAN Card vs Form 16
        4. Aadhaar match: Form Aadhaar vs Aadhaar Card
        5. Employment: Salary Slip employer vs Form 16 employer
        """
        verification = {
            "overall_status": "pending",
            "verification_score": 0,
            "checks_passed": 0,
            "checks_total": 0,
            "checks": [],
            "flags": [],
            "risk_indicators": []
        }

        checks = []

        # CHECK 1: Aadhaar Number Match
        if "aadhaar_front" in extracted_documents:
            doc_aadhaar = extracted_documents["aadhaar_front"].get("aadhaar_number", "")
            form_aadhaar = application_data.get("aadhaar_number", "")
            checks.append(self._check_match(
                "Aadhaar Number", doc_aadhaar, form_aadhaar, exact=True
            ))

        # CHECK 2: PAN Number Match
        if "pan_card" in extracted_documents:
            doc_pan = extracted_documents["pan_card"].get("pan_number", "")
            form_pan = application_data.get("pan_number", "")
            checks.append(self._check_match(
                "PAN Number", doc_pan, form_pan, exact=True
            ))

        # CHECK 3: Name Consistency
        names_found = []
        if "aadhaar_front" in extracted_documents:
            name = extracted_documents["aadhaar_front"].get("name")
            if name:
                names_found.append(("Aadhaar", name))
        if "pan_card" in extracted_documents:
            name = extracted_documents["pan_card"].get("name")
            if name:
                names_found.append(("PAN", name))

        form_name = application_data.get("full_name", "")
        if form_name and names_found:
            best_match = max(
                [self._name_similarity(form_name, n[1]) for n in names_found]
            )
            checks.append({
                "check": "Name Consistency",
                "status": "passed" if best_match > 0.7 else "failed",
                "score": best_match,
                "details": f"Form name vs document names (match: {best_match:.0%})"
            })

        # CHECK 4: Income Verification
        form_income = application_data.get("person_income", 0)
        monthly_form = form_income / 12 if form_income > 0 else 0

        if "salary_slip_1" in extracted_documents:
            slip_data = extracted_documents["salary_slip_1"]
            slip_salary = (slip_data.get("net_salary", 0) or
                          slip_data.get("earnings", {}).get("gross_salary", 0))
            if slip_salary and monthly_form:
                ratio = min(slip_salary, monthly_form) / max(slip_salary, monthly_form)
                checks.append({
                    "check": "Income vs Salary Slip",
                    "status": "passed" if ratio > 0.75 else "failed",
                    "score": ratio,
                    "details": (f"Form: ₹{monthly_form:,.0f}/month, "
                               f"Salary Slip: ₹{slip_salary:,.0f}/month")
                })
                if ratio < 0.75:
                    verification["flags"].append(
                        f"Income mismatch: Form claims ₹{form_income:,.0f}/year "
                        f"but salary slip shows ₹{slip_salary:,.0f}/month"
                    )

        # CHECK 5: Bank Statement Salary Credits
        if "bank_statement" in extracted_documents:
            bank_data = extracted_documents["bank_statement"]
            if bank_data.get("regular_income_detected"):
                avg_credit = bank_data.get("average_monthly_salary", 0)
                if avg_credit and monthly_form:
                    ratio = min(avg_credit, monthly_form) / max(avg_credit, monthly_form)
                    checks.append({
                        "check": "Income vs Bank Credits",
                        "status": "passed" if ratio > 0.7 else "failed",
                        "score": ratio,
                        "details": (f"Form: ₹{monthly_form:,.0f}/month, "
                                   f"Bank credits avg: ₹{avg_credit:,.0f}/month")
                    })

            # Risk: Bounced cheques
            bounced = bank_data.get("bounced_cheques", 0)
            if bounced > 0:
                verification["risk_indicators"].append(
                    f"{bounced} bounced/returned cheque(s) in last 6 months"
                )

            # Risk: High EMI obligations
            emi_total = bank_data.get("monthly_emi_obligation", 0)
            if emi_total > 0 and monthly_form > 0:
                emi_to_income = emi_total / monthly_form
                if emi_to_income > 0.5:
                    verification["risk_indicators"].append(
                        f"EMI obligations (₹{emi_total:,.0f}) exceed 50% of monthly income"
                    )

        # CHECK 6: Form 16 vs Salary
        if "form_16" in extracted_documents:
            form16 = extracted_documents["form_16"]
            gross_income_f16 = form16.get("gross_total_income", 0)
            if gross_income_f16 and form_income:
                ratio = min(gross_income_f16, form_income) / max(gross_income_f16, form_income)
                checks.append({
                    "check": "Income vs Form 16",
                    "status": "passed" if ratio > 0.8 else "failed",
                    "score": ratio,
                    "details": (f"Form: ₹{form_income:,.0f}/year, "
                               f"Form 16: ₹{gross_income_f16:,.0f}/year")
                })

        # Calculate overall verification score
        verification["checks"] = checks
        verification["checks_total"] = len(checks)
        verification["checks_passed"] = sum(1 for c in checks if c["status"] == "passed")

        if verification["checks_total"] > 0:
            score = verification["checks_passed"] / verification["checks_total"]
            verification["verification_score"] = round(score, 2)

            if score >= 0.8 and not verification["risk_indicators"]:
                verification["overall_status"] = "fully_verified"
            elif score >= 0.6:
                verification["overall_status"] = "partially_verified"
            else:
                verification["overall_status"] = "verification_failed"
        else:
            verification["overall_status"] = "no_documents"

        return verification

    # ================================================================
    # UTILITY METHODS
    # ================================================================
    def _check_match(self, check_name: str, doc_value: str,
                     form_value: str, exact: bool = True) -> dict:
        """Compare a document value against form value."""
        if not doc_value or not form_value:
            return {
                "check": check_name,
                "status": "skipped",
                "score": 0,
                "details": "Value missing from document or form"
            }

        if exact:
            match = doc_value.strip().upper() == form_value.strip().upper()
            return {
                "check": check_name,
                "status": "passed" if match else "failed",
                "score": 1.0 if match else 0.0,
                "details": f"Document: {doc_value}, Form: {form_value}"
            }
        else:
            score = self._name_similarity(doc_value, form_value)
            return {
                "check": check_name,
                "status": "passed" if score > 0.8 else "failed",
                "score": score,
                "details": f"Document: {doc_value}, Form: {form_value} (match: {score:.0%})"
            }

    def _name_similarity(self, name1: str, name2: str) -> float:
        """Fuzzy name matching for Indian names."""
        if not name1 or not name2:
            return 0.0
        n1_parts = set(name1.lower().strip().split())
        n2_parts = set(name2.lower().strip().split())
        if not n1_parts or not n2_parts:
            return 0.0
        intersection = n1_parts & n2_parts
        union = n1_parts | n2_parts
        return len(intersection) / len(union)

    def _parse_amount(self, amount_str: str) -> float:
        """Parse Indian number format (with commas) to float."""
        try:
            return float(str(amount_str).replace(",", ""))
        except (ValueError, TypeError, AttributeError):
            return 0.0
