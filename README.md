# Techno Serverless OMS

## Project Structure

```
Serverprov/
├── lambda/                     ← Lambda function source code (reference)
│   ├── order_management/
│   │   ├── lambda_function.py
│   │   └── README.md           ← Environment variables & usage
│   ├── process_payment/
│   ├── update_inventory/
│   ├── send_notification/
│   ├── generate_report/
│   ├── init_db/
│   ├── health_check/
│   └── requirements.txt
├── frontend/
│   └── index.html              ← Dashboard frontend
├── codedeploy/
│   └── appspec.yml
├── .github/workflows/
│   └── deploy.yml              ← GitHub Actions CI/CD pipeline
└── amplify.yml
```

## What Students Must Build

| Component | Notes |
|-----------|-------|
| CloudFormation (7 stacks) | Build from scratch via AWS Console |
| Step Functions ASL | Build from scratch via Workflow Studio |
| Lambda Layer | Build and upload manually |
| Upload Lambda code | Upload to each function after stack deployment. |

---


## Test the API

```bash
API_URL="https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/production"
API_KEY="YOUR_API_KEY"

# Health check
curl -s -H "x-api-key: $API_KEY" "$API_URL/health" | python3 -m json.tool

# Create an order
curl -s -X POST "$API_URL/orders" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"customerId":"CUST001","items":[{"productId":"PROD001","quantity":2}],"totalAmount":50000}' \
  | python3 -m json.tool
```

## Setup CI/CD (GitHub Actions)

Add secrets in your GitHub repository:

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | From Learner Lab |
| `AWS_SECRET_ACCESS_KEY` | From Learner Lab |
| `AWS_SESSION_TOKEN` | From Learner Lab |
| `SNS_TOPIC_ARN` | SNS Topic ARN |
| `S3_DEPLOYMENT_BUCKET` | Logs bucket name |
| `AMPLIFY_APP_ID` | Amplify App ID (format: `dXXXXXXXX`) |

---

## Lambda Function Reference

| Function | Purpose | README |
|----------|---------|--------|
| `order_management` | Order CRUD, validation, DB queries | [README](lambda/order_management/README.md) |
| `process_payment` | Payment processing | [README](lambda/process_payment/README.md) |
| `update_inventory` | Update product stock | [README](lambda/update_inventory/README.md) |
| `send_notification` | Send email via SNS | [README](lambda/send_notification/README.md) |
| `generate_report` | Generate reports to S3 | [README](lambda/generate_report/README.md) |
| `init_db` | Initialize tables and sample data | [README](lambda/init_db/README.md) |
| `health_check` | Check health of all services | [README](lambda/health_check/README.md) |

---