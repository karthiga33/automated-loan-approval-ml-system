# Deploy Loan Approval System: EC2 + CloudFront

## Architecture
```
User Browser → CloudFront (HTTPS, global CDN) → EC2 (Flask app on port 8000)
```

---

## Step 1: Launch an EC2 Instance

1. Go to **AWS Console → EC2 → Launch Instance**
2. Settings:
   - **Name:** `loan-approval-server`
   - **AMI:** Amazon Linux 2023 (or Ubuntu 22.04)
   - **Instance type:** `t2.micro` (free tier) or `t3.small` for better performance
   - **Key pair:** Create new or select existing (.pem file — save it!)
   - **Network settings:**
     - Allow SSH (port 22) from your IP
     - Allow HTTP (port 80) from anywhere
     - Allow Custom TCP (port 8000) from anywhere
   - **Storage:** 20 GB gp3
3. Click **Launch Instance**
4. Note down the **Public IP** (e.g., `3.110.45.123`)

---

## Step 2: Connect to EC2

```bash
# From your terminal (replace with your .pem path and EC2 IP)
chmod 400 your-key.pem
ssh -i your-key.pem ec2-user@<EC2-PUBLIC-IP>

# If Ubuntu:
# ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>
```

---

## Step 3: Install Dependencies on EC2

### For Amazon Linux 2023:
```bash
sudo yum update -y
sudo yum install -y python3 python3-pip git
```

### For Ubuntu:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip git
```

---

## Step 4: Upload Your Code to EC2

### Option A: Using SCP (from your Windows machine)
```bash
# From your local Windows terminal (PowerShell):
scp -i your-key.pem -r "C:\Users\KarthigaS\Downloads\Bank_Approval\Bank_Approval\Automated-Loan-Approval-ML-System" ec2-user@<EC2-IP>:~/loan-app
```

### Option B: Using Git
```bash
# On EC2, if your code is in a git repo:
git clone <your-repo-url> ~/loan-app
```

---

## Step 5: Install Python Packages on EC2

```bash
cd ~/loan-app
pip3 install flask pandas numpy scikit-learn joblib gunicorn
```

---

## Step 6: Test the App

```bash
cd ~/loan-app
python3 app_local.py
```
Open `http://<EC2-PUBLIC-IP>:8000` in your browser. If it works, stop it (Ctrl+C).

---

## Step 7: Run with Gunicorn (Production)

Gunicorn is a production-ready WSGI server (better than Flask dev server):

```bash
cd ~/loan-app
gunicorn --bind 0.0.0.0:8000 --workers 3 --timeout 120 app_local:app
```

Test: `http://<EC2-PUBLIC-IP>:8000`

---

## Step 8: Run as a Background Service (Systemd)

Create a service so the app starts automatically and survives reboots:

```bash
sudo tee /etc/systemd/system/loanapp.service << 'EOF'
[Unit]
Description=Loan Approval Flask App
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/loan-app
ExecStart=/usr/local/bin/gunicorn --bind 0.0.0.0:8000 --workers 3 --timeout 120 app_local:app
Restart=always
RestartSec=5
Environment=PATH=/usr/local/bin:/usr/bin

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable loanapp
sudo systemctl start loanapp
sudo systemctl status loanapp
```

Check logs if needed:
```bash
sudo journalctl -u loanapp -f
```

---

## Step 9: Set Up CloudFront

1. Go to **AWS Console → CloudFront → Create Distribution**

2. **Origin Settings:**
   - Origin domain: `<EC2-PUBLIC-IP>` (or use an Elastic IP for stability)
   - Protocol: **HTTP only**
   - HTTP port: **8000**
   - Origin path: leave empty

3. **Default Cache Behavior:**
   - Viewer protocol policy: **Redirect HTTP to HTTPS**
   - Allowed HTTP methods: **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE**
   - Cache policy: **CachingDisabled** (since this is a dynamic app)
   - Origin request policy: **AllViewer**

4. **Settings:**
   - Price class: Use all edge locations (or just your region)
   - Default root object: leave empty (Flask handles `/`)

5. Click **Create Distribution**

6. Wait 5-10 minutes for deployment. You'll get a URL like:
   ```
   https://d1234abcdef.cloudfront.net
   ```

---

## Step 10: Access Your App

Open in any browser:
```
https://d1234abcdef.cloudfront.net
```

All pages work:
- `/` — Home (apply for loan)
- `/track` — Track application
- `/tracker` — Loan repayment tracker
- `/admin` — Admin dashboard
- `/emi` — EMI calculator
- `/eligibility` — Eligibility check

---

## Important Notes

### Use Elastic IP (Recommended)
If your EC2 stops/starts, the public IP changes and CloudFront breaks.
Fix: **EC2 → Elastic IPs → Allocate → Associate** with your instance.

### Security Group Rules
Make sure your EC2 security group allows:
| Type | Port | Source |
|------|------|--------|
| SSH | 22 | Your IP |
| Custom TCP | 8000 | CloudFront IPs (or 0.0.0.0/0 for simplicity) |

### Cost Estimate (Monthly)
- EC2 t2.micro: Free tier (first year) or ~$8/month
- CloudFront: Free tier covers 1TB/month, then ~$0.085/GB
- Elastic IP (while attached): Free

### Troubleshooting
```bash
# Check if app is running
sudo systemctl status loanapp

# Check logs
sudo journalctl -u loanapp --no-pager -n 50

# Restart app
sudo systemctl restart loanapp

# Test locally on EC2
curl http://localhost:8000/health
```
