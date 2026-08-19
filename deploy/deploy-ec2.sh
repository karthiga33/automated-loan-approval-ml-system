#!/bin/bash
# ============================================================
# Loan Approval System - EC2 API Deployment
# Run this ON the EC2 instance after SSH'ing in
# ============================================================

set -e

echo "=========================================="
echo " LOAN APPROVAL SYSTEM - EC2 API SETUP"
echo "=========================================="

# Update system
echo "[1/5] Updating system..."
sudo yum update -y
sudo yum install python3-pip git -y

# Clone repo (if not already present)
echo "[2/5] Setting up project..."
if [ ! -d "Automated-Loan-Approval-ML-System" ]; then
    git clone https://github.com/msardamasri/Automated-Loan-Approval-ML-System.git
fi
cd Automated-Loan-Approval-ML-System

# Install dependencies
echo "[3/5] Installing Python dependencies..."
pip3 install flask boto3 pandas numpy scikit-learn joblib --quiet

# Set environment variables
echo "[4/5] Configuring environment..."
export AWS_REGION=us-east-1
export S3_BUCKET_NAME=loan-approval-ml-system
export DYNAMODB_TABLE=LoanApprovalDecisions
export CIBIL_MODE=mock
export API_PORT=8000
export JWT_SECRET_KEY=$(python3 -c "import uuid; print(uuid.uuid4().hex)")

# Create systemd service for auto-start
echo "[5/5] Creating system service..."
sudo tee /etc/systemd/system/loan-approval-api.service > /dev/null <<EOF
[Unit]
Description=Loan Approval ML API
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/Automated-Loan-Approval-ML-System
Environment="AWS_REGION=us-east-1"
Environment="S3_BUCKET_NAME=loan-approval-ml-system"
Environment="DYNAMODB_TABLE=LoanApprovalDecisions"
Environment="CIBIL_MODE=mock"
Environment="API_PORT=8000"
ExecStart=/usr/bin/python3 /home/ec2-user/Automated-Loan-Approval-ML-System/api/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable loan-approval-api
sudo systemctl start loan-approval-api

echo ""
echo "=========================================="
echo " EC2 API DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo " API is running on port 8000"
echo ""
echo " Endpoints:"
echo "   GET  http://YOUR_EC2_IP:8000/         - Customer Portal"
echo "   GET  http://YOUR_EC2_IP:8000/health   - Health Check"
echo "   POST http://YOUR_EC2_IP:8000/api/applications/submit"
echo ""
echo " Service commands:"
echo "   sudo systemctl status loan-approval-api"
echo "   sudo systemctl restart loan-approval-api"
echo "   sudo journalctl -u loan-approval-api -f"
echo "=========================================="
