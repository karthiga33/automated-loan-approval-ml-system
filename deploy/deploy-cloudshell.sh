#!/bin/bash
# ============================================================
# Loan Approval System - CloudShell Deployment Script
# Run this in AWS CloudShell after cloning the repository
# ============================================================

set -e

echo "=========================================="
echo " LOAN APPROVAL SYSTEM - DEPLOYMENT"
echo "=========================================="

# Configuration
BUCKET_NAME="loan-approval-ml-system"
REGION="us-east-1"
STACK_NAME="loan-approval-system"
DYNAMODB_TABLE="LoanApprovalDecisions"
DOCUMENTS_TABLE="LoanApprovalDocuments"

echo ""
echo "[1/7] Creating S3 Bucket..."
echo "-------------------------------------------"
aws s3 mb s3://${BUCKET_NAME} --region ${REGION} 2>/dev/null || echo "Bucket already exists"
aws s3api put-bucket-versioning \
    --bucket ${BUCKET_NAME} \
    --versioning-configuration Status=Enabled

# Block public access
aws s3api put-public-access-block \
    --bucket ${BUCKET_NAME} \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "✓ S3 Bucket ready: ${BUCKET_NAME}"

echo ""
echo "[2/7] Creating DynamoDB Tables..."
echo "-------------------------------------------"
# Decisions table
aws dynamodb create-table \
    --table-name ${DYNAMODB_TABLE} \
    --attribute-definitions \
        AttributeName=application_id,AttributeType=S \
        AttributeName=date,AttributeType=S \
    --key-schema \
        AttributeName=application_id,KeyType=HASH \
        AttributeName=date,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region ${REGION} 2>/dev/null || echo "Table ${DYNAMODB_TABLE} already exists"

# Documents table
aws dynamodb create-table \
    --table-name ${DOCUMENTS_TABLE} \
    --attribute-definitions \
        AttributeName=application_id,AttributeType=S \
        AttributeName=document_type,AttributeType=S \
    --key-schema \
        AttributeName=application_id,KeyType=HASH \
        AttributeName=document_type,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region ${REGION} 2>/dev/null || echo "Table ${DOCUMENTS_TABLE} already exists"

echo "✓ DynamoDB Tables ready"

echo ""
echo "[3/7] Creating IAM Role..."
echo "-------------------------------------------"
# Create role
aws iam create-role \
    --role-name LoanApprovalLambdaRole \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' 2>/dev/null || echo "Role already exists"

# Attach policies
aws iam attach-role-policy \
    --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null || true

aws iam attach-role-policy \
    --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess 2>/dev/null || true

aws iam attach-role-policy \
    --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess 2>/dev/null || true

aws iam attach-role-policy \
    --role-name LoanApprovalLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonTextractFullAccess 2>/dev/null || true

echo "✓ IAM Role configured"
echo "  (Waiting 10s for role propagation...)"
sleep 10

echo ""
echo "[4/7] Creating S3 folder structure..."
echo "-------------------------------------------"
# Create folder structure
aws s3api put-object --bucket ${BUCKET_NAME} --key "raw/" --content-length 0
aws s3api put-object --bucket ${BUCKET_NAME} --key "processed/" --content-length 0
aws s3api put-object --bucket ${BUCKET_NAME} --key "predictions/" --content-length 0
aws s3api put-object --bucket ${BUCKET_NAME} --key "models/" --content-length 0
aws s3api put-object --bucket ${BUCKET_NAME} --key "applications/" --content-length 0
aws s3api put-object --bucket ${BUCKET_NAME} --key "documents/" --content-length 0

echo "✓ S3 folder structure created"

echo ""
echo "[5/7] Training and uploading ML model..."
echo "-------------------------------------------"
pip3 install pandas scikit-learn joblib numpy imbalanced-learn --quiet

python3 - <<'EOF'
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OrdinalEncoder
from sklearn.compose import ColumnTransformer
import joblib
import os

print("Loading training data...")
data_path = "data/loan-data.csv"
if os.path.exists(data_path):
    df = pd.read_csv(data_path)
    print(f"  Loaded {len(df)} records")
    
    # Define features
    numeric_features = ['person_age', 'person_income', 'person_emp_exp', 'loan_amnt',
                       'loan_int_rate', 'loan_percent_income', 'cb_person_cred_hist_length']
    categorical_features = ['person_gender', 'employment_type', 'person_home_ownership',
                           'loan_intent', 'account_type', 'person_education',
                           'previous_loan_defaults_on_file']
    
    all_features = numeric_features + categorical_features
    target = 'loan_status'
    
    # Filter to available columns
    available_features = [f for f in all_features if f in df.columns]
    
    if target in df.columns:
        X = df[available_features].copy()
        y = df[target].copy()
        
        # Handle missing values
        for col in numeric_features:
            if col in X.columns:
                X[col] = X[col].fillna(X[col].median())
        for col in categorical_features:
            if col in X.columns:
                X[col] = X[col].fillna('Unknown')
        
        # Create preprocessing pipeline
        numeric_transformer = StandardScaler()
        categorical_transformer = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
        
        available_numeric = [f for f in numeric_features if f in X.columns]
        available_categorical = [f for f in categorical_features if f in X.columns]
        
        preprocessor = ColumnTransformer(
            transformers=[
                ('num', numeric_transformer, available_numeric),
                ('cat', categorical_transformer, available_categorical)
            ])
        
        # Create full pipeline
        pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('classifier', RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            ))
        ])
        
        # Train
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        print("Training Random Forest model...")
        pipeline.fit(X_train, y_train)
        
        # Evaluate
        accuracy = pipeline.score(X_test, y_test)
        print(f"  Model accuracy: {accuracy:.4f}")
        
        # Save model
        model_path = "/tmp/loan_approval_pipeline.pkl"
        joblib.dump(pipeline, model_path)
        print(f"  Model saved to {model_path}")
        
        # Upload to S3
        import boto3
        s3 = boto3.client('s3')
        s3.upload_file(model_path, 'loan-approval-ml-system', 'models/loan_approval_pipeline.pkl')
        print("  Model uploaded to S3")
    else:
        print(f"  Target column '{target}' not found. Available columns: {list(df.columns)}")
else:
    print(f"  Training data not found at {data_path}")
    print("  Please upload loan-data.csv to the data/ folder")
EOF

echo "✓ ML Model trained and uploaded"

echo ""
echo "[6/7] Deploying Lambda Functions..."
echo "-------------------------------------------"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/LoanApprovalLambdaRole"

# Package and deploy each Lambda
cd lambdas

# Lambda 1: Extractor
echo "  Deploying loan-approval-extractor..."
zip -q lambda-loan-extractor.zip lambda-loan-extractor.py
aws lambda create-function \
    --function-name loan-approval-extractor \
    --runtime python3.9 \
    --role ${ROLE_ARN} \
    --handler lambda-loan-extractor.lambda_handler \
    --zip-file fileb://lambda-loan-extractor.zip \
    --timeout 60 \
    --memory-size 256 \
    --environment "Variables={S3_BUCKET_NAME=${BUCKET_NAME}}" \
    --region ${REGION} 2>/dev/null || \
aws lambda update-function-code \
    --function-name loan-approval-extractor \
    --zip-file fileb://lambda-loan-extractor.zip \
    --region ${REGION}

# Lambda 2: Processor
echo "  Deploying loan-approval-processor..."
zip -q lambda-loan-processor.zip lambda-loan-processor.py
aws lambda create-function \
    --function-name loan-approval-processor \
    --runtime python3.9 \
    --role ${ROLE_ARN} \
    --handler lambda-loan-processor.lambda_handler \
    --zip-file fileb://lambda-loan-processor.zip \
    --timeout 120 \
    --memory-size 512 \
    --environment "Variables={S3_BUCKET_NAME=${BUCKET_NAME}}" \
    --region ${REGION} 2>/dev/null || \
aws lambda update-function-code \
    --function-name loan-approval-processor \
    --zip-file fileb://lambda-loan-processor.zip \
    --region ${REGION}

# Lambda 3: Predictor
echo "  Deploying loan-approval-predictor..."
zip -q lambda-loan-predictor.zip lambda-loan-predictor.py
aws lambda create-function \
    --function-name loan-approval-predictor \
    --runtime python3.9 \
    --role ${ROLE_ARN} \
    --handler lambda-loan-predictor.lambda_handler \
    --zip-file fileb://lambda-loan-predictor.zip \
    --timeout 300 \
    --memory-size 1024 \
    --environment "Variables={S3_BUCKET_NAME=${BUCKET_NAME},DYNAMODB_TABLE=${DYNAMODB_TABLE},MODEL_KEY=models/loan_approval_pipeline.pkl}" \
    --region ${REGION} 2>/dev/null || \
aws lambda update-function-code \
    --function-name loan-approval-predictor \
    --zip-file fileb://lambda-loan-predictor.zip \
    --region ${REGION}

# Lambda 4: Document Processor
echo "  Deploying loan-approval-document-processor..."
zip -q lambda-document-processor.zip lambda-document-processor.py
aws lambda create-function \
    --function-name loan-approval-document-processor \
    --runtime python3.9 \
    --role ${ROLE_ARN} \
    --handler lambda-document-processor.lambda_handler \
    --zip-file fileb://lambda-document-processor.zip \
    --timeout 120 \
    --memory-size 512 \
    --environment "Variables={S3_BUCKET_NAME=${BUCKET_NAME},DOCUMENTS_TABLE=${DOCUMENTS_TABLE}}" \
    --region ${REGION} 2>/dev/null || \
aws lambda update-function-code \
    --function-name loan-approval-document-processor \
    --zip-file fileb://lambda-document-processor.zip \
    --region ${REGION}

# Clean up zip files
rm -f *.zip
cd ..

echo "✓ Lambda Functions deployed"

echo ""
echo "[7/7] Setting up S3 Event Trigger for Document Processing..."
echo "-------------------------------------------"
# Add permission for S3 to invoke Lambda
aws lambda add-permission \
    --function-name loan-approval-document-processor \
    --statement-id s3-trigger \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn "arn:aws:s3:::${BUCKET_NAME}" \
    --region ${REGION} 2>/dev/null || true

echo "✓ Event trigger configured"

echo ""
echo "=========================================="
echo " DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo " Resources Created:"
echo "   • S3 Bucket: ${BUCKET_NAME}"
echo "   • DynamoDB:  ${DYNAMODB_TABLE}"
echo "   • DynamoDB:  ${DOCUMENTS_TABLE}"
echo "   • Lambda:    loan-approval-extractor"
echo "   • Lambda:    loan-approval-processor"
echo "   • Lambda:    loan-approval-predictor"
echo "   • Lambda:    loan-approval-document-processor"
echo "   • IAM Role:  LoanApprovalLambdaRole"
echo ""
echo " Next Steps:"
echo "   1. Deploy EC2 API:  See deploy/deploy-ec2.sh"
echo "   2. Test the system: See deploy/test-system.sh"
echo ""
echo " Estimated Monthly Cost (Free Tier):"
echo "   • Lambda:   FREE (1M requests/month)"
echo "   • S3:       FREE (5GB storage)"
echo "   • DynamoDB: FREE (25 RCU + 25 WCU)"
echo "   • Textract: FREE (1000 pages/month for 3 months)"
echo "=========================================="
