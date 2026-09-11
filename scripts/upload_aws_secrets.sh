#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_FILE="${ROOT_DIR}/secrets.local.json"
TERRAFORM_DIR="${ROOT_DIR}/infra/secrets"

if [[ ! -f "${SECRET_FILE}" ]]; then
  echo "Missing ${SECRET_FILE}"
  exit 1
fi

if grep -q "PASTE_.*_HERE" "${SECRET_FILE}"; then
  echo "secrets.local.json still has placeholder values. Fill it in before uploading."
  exit 1
fi

SECRET_ID=""

if command -v terraform >/dev/null 2>&1 && [[ -d "${TERRAFORM_DIR}/.terraform" ]]; then
  SECRET_ID="$(cd "${TERRAFORM_DIR}" && terraform output -raw app_secret_arn 2>/dev/null || true)"
fi

if [[ -z "${SECRET_ID}" && -f "${ROOT_DIR}/.env" ]]; then
  SECRET_ID="$(
    awk -F= '/^BLUEGRASS_SECRET_ARN=/ {print $2; exit}' "${ROOT_DIR}/.env" \
      | sed 's/^["'\'']//; s/["'\'']$//'
  )"
fi

if [[ -z "${SECRET_ID}" || "${SECRET_ID}" == "PASTE_TERRAFORM_APP_SECRET_ARN_HERE" ]]; then
  cat <<'EOF'
No AWS Secrets Manager ARN found.

Do one of these first:

1. Create the secret with Terraform:
   cd infra/secrets
   terraform init
   terraform apply

2. Or paste an existing secret ARN into .env:
   BLUEGRASS_SECRET_ARN=arn:aws:secretsmanager:...

Then rerun:
   ./scripts/upload_aws_secrets.sh
EOF
  exit 1
fi

aws secretsmanager put-secret-value \
  --secret-id "${SECRET_ID}" \
  --secret-string "file://${SECRET_FILE}"

echo "Uploaded secrets to ${SECRET_ID}"
echo "You can now delete ${SECRET_FILE}; AWS Secrets Manager has the current version."
