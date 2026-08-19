"""
Lambda: Document Processor
Triggered when a document is uploaded to S3.
Uses AWS Textract to extract text and verify against application data.
"""
import json
import boto3
import re
import os
from datetime import datetime

# AWS clients
s3 = boto3.client("s3")
textract = boto3.client("textract")
dynamodb = boto3.resource("dynamodb")

BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "loan-approval-ml-system")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "LoanApprovalDocuments")


def lambda_handler(event, context):
    """
    Process uploaded documents using AWS Textract.
    Triggered by S3 event when document is uploaded to applications/{id}/documents/
    """
    print("=== DOCUMENT PROCESSOR ===")
    print(f"Timestamp: {datetime.now().isoformat()}")

    try:
        # Get S3 event details
        for record in event.get("Records", []):
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]

            print(f"Processing document: s3://{bucket}/{key}")

            # Extract application_id and document_type from key
            # Format: applications/{app_id}/documents/{doc_type}_{uuid}
            parts = key.split("/")
            if len(parts) < 4:
                print(f"Unexpected key format: {key}")
                continue

            application_id = parts[1]
            doc_filename = parts[3]
            document_type = doc_filename.split("_")[0]

            print(f"Application: {application_id}, Document: {document_type}")

            # Call Textract
            extracted_data = extract_text_from_document(bucket, key)

            # Parse extracted text based on document type
            parsed_data = parse_document(document_type, extracted_data)

            # Store results in DynamoDB
            table = dynamodb.Table(DOCUMENTS_TABLE)
            table.put_item(Item={
                "application_id": application_id,
                "document_type": document_type,
                "s3_key": key,
                "extracted_data": json.dumps(parsed_data),
                "status": "processed",
                "processed_at": datetime.now().isoformat()
            })

            print(f"Document processed and stored for {application_id}")

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Documents processed successfully"})
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


def extract_text_from_document(bucket: str, key: str) -> str:
    """Extract text from document using AWS Textract."""
    try:
        response = textract.detect_document_text(
            Document={
                "S3Object": {
                    "Bucket": bucket,
                    "Name": key
                }
            }
        )

        lines = []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                lines.append(block["Text"])

        return "\n".join(lines)

    except Exception as e:
        print(f"Textract error: {e}")
        return ""


def parse_document(document_type: str, text: str) -> dict:
    """Parse extracted text based on document type."""
    if document_type == "aadhaar":
        return parse_aadhaar(text)
    elif document_type == "pan":
        return parse_pan(text)
    elif document_type == "salary":
        return parse_salary_slip(text)
    elif document_type == "bank":
        return parse_bank_statement(text)
    else:
        return {"raw_text": text[:500], "type": document_type}


def parse_aadhaar(text: str) -> dict:
    """Extract data from Aadhaar card."""
    data = {"name": None, "dob": None, "aadhaar_number": None, "gender": None}

    for line in text.split("\n"):
        # Aadhaar number: 12 digits
        match = re.search(r"\d{4}\s?\d{4}\s?\d{4}", line)
        if match:
            data["aadhaar_number"] = match.group().replace(" ", "")

        # DOB
        dob_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
        if dob_match:
            data["dob"] = dob_match.group()

        # Gender
        if "male" in line.lower() and "female" not in line.lower():
            data["gender"] = "Male"
        elif "female" in line.lower():
            data["gender"] = "Female"

    return data


def parse_pan(text: str) -> dict:
    """Extract data from PAN card."""
    data = {"pan_number": None, "name": None, "dob": None}

    for line in text.split("\n"):
        # PAN format: ABCDE1234F
        match = re.search(r"[A-Z]{5}\d{4}[A-Z]", line)
        if match:
            data["pan_number"] = match.group()

        # DOB
        dob_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
        if dob_match:
            data["dob"] = dob_match.group()

    return data


def parse_salary_slip(text: str) -> dict:
    """Extract salary data from salary slip."""
    data = {"gross_salary": None, "net_salary": None, "deductions": None}

    for line in text.split("\n"):
        lower = line.lower()
        amounts = re.findall(r"[\d,]+\.?\d*", line)

        if "gross" in lower and amounts:
            data["gross_salary"] = parse_amount(amounts[-1])
        elif "net" in lower and amounts:
            data["net_salary"] = parse_amount(amounts[-1])
        elif "deduction" in lower and amounts:
            data["deductions"] = parse_amount(amounts[-1])

    return data


def parse_bank_statement(text: str) -> dict:
    """Extract key data from bank statement."""
    data = {"salary_credits": [], "account_number": None}

    for line in text.split("\n"):
        if "salary" in line.lower() or "sal" in line.lower():
            amounts = re.findall(r"[\d,]+\.?\d*", line)
            for amt in amounts:
                val = parse_amount(amt)
                if val > 10000:
                    data["salary_credits"].append(val)

        # Account number
        acc_match = re.search(r"\d{10,18}", line)
        if acc_match and not data["account_number"]:
            data["account_number"] = acc_match.group()

    return data


def parse_amount(amount_str: str) -> float:
    """Parse amount string to float."""
    try:
        return float(amount_str.replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0
