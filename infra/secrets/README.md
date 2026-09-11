# AWS Secrets Manager

Terraform tracks the Secrets Manager secret container. The actual secret values are uploaded with AWS CLI so credentials do not enter Terraform state or git.

## 1. Configure AWS CLI

```bash
aws configure
aws sts get-caller-identity
```

Use an AWS identity that can manage Secrets Manager in the target account.

## 2. Create the secret container

```bash
cd infra/secrets
terraform init
terraform apply
```

Copy the `app_secret_arn` output.

## 3. Upload secret values

Copy the example to a temporary local file and fill it in. `secrets.local.json` is gitignored and should be deleted after upload.

```bash
cd ../..
cp secrets.local.example.json secrets.local.json
```

```json
{
  "OPENAI_API_KEY": "sk-...",
  "XAI_API_KEY": "xai-...",
  "IMGFLIP_USERNAME": "...",
  "IMGFLIP_PASSWORD": "...",
  "REDDIT_CLIENT_ID": "...",
  "REDDIT_CLIENT_SECRET": "...",
  "APIFY_API_TOKEN": "...",
  "KLING_API_KEY": "...",
  "ELEVENLABS_API_KEY": "..."
}
```

Then upload it:

```bash
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw app_secret_arn)" \
  --secret-string file://../../secrets.local.json
```

After upload succeeds, delete the filled local file:

```bash
rm ../../secrets.local.json
```

## 4. Run the app against AWS secrets

Set the secret ARN in `.env`:

```bash
BLUEGRASS_SECRET_ARN=arn:aws:secretsmanager:...
AWS_REGION=us-east-1
```

The app checks AWS Secrets Manager first, then falls back to ordinary `.env` values. The intended AWS setup is to keep only the ARN and region in `.env`; provider API keys should live in Secrets Manager.

## Notes

- Do not add `aws_secretsmanager_secret_version` with real values unless you accept secrets being stored in Terraform state.
- A new OpenAI key will not fix `insufficient_quota` unless it belongs to an OpenAI API project with billing/quota.
- You can rotate a provider key by editing `secrets.local.json` and running `aws secretsmanager put-secret-value` again.
