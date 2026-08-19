#!/bin/bash
# ============================================================
# Loan Approval System - Cleanup Script
# Removes all AWS resources (run in CloudShell)
# WARNING: This is destructive and irreversible!
# ============================================================

echo "=========================================="
echo " LOAN APPROVAL SYSTEM - CLEANUP"
echo " WARNING: This will DELETE all resources!"
echo "=========================================="
read -p "Are you sure? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

BUCKET_NAME="loan-approval-ml-system"
REGION="us-east-1"

echo ""
echo "[1/5] Deleting Lambda Functions..."
aws lambda delete-function --function-name loan-approval-extractor --region ${REGION} 2>/dev/null || true
aws lambda delete-function --function-name loan-approval-processor --region ${REGION} 2>/dev/null || true
aws lambda delete-function --function-name loan-approval-predictor --region ${REGION} 2>/dev/null || true
aws lambda delete-function --function-name loan-approval-document-processor --region ${REGION} 2>/dev/null || true
echo "✓ Lambda Functions deleted"

echo ""
echo "[2/5] Deleting S3 Bucket..."
aws s3 rm s3://${BUCKET_NAME} --recursive --region ${REGION} 2>/dev/null || true
aws s3 rb s3://${BUCKET_NAME} --region ${REGION} 2>/dev/null || true
echo "✓ S3 Bucket deleted"

echo ""
echo "[3/5] Deleting DynamoDB Tables..."
aws dynamodb delete-table --table-name LoanApprovalDecisions --region ${REGION} 2>/dev/null || true
aws dynamodb delete-table --table-name LoanApprovalDocuments --region ${REGION} 2>/dev/null || true
echo "✓ DynamoDB Tables deleted"

echo ""
echo "[4/5] Deleting IAM Role..."
aws iam detach-role-policy --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true
aws iam detach-role-policy --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess 2>/dev/null || true
aws iam detach-role-policy --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess 2>/dev/null || true
aws iam detach-role-policy --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonTextractFullAccess 2>/dev/null || true
aws iam delete-role --role-name LoanApprovalLambdaRole 2>/dev/null || true
echo "✓ IAM Role deleted"

echo ""
echo "[5/5] Terminating EC2 Instance (if any)..."
echo "  Note: You need to terminate EC2 manually from the console"
echo "  or provide the instance ID"
echo ""

echo "=========================================="
echo " CLEANUP COMPLETE"
echo "=========================================="
echo " All Loan Approval System resources removed."
echo "=========================================="
