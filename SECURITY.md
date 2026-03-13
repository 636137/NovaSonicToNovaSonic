# Security Policy (Maximus Internal)

> **Confidential — Maximus Internal Use Only**

## Credential and Secret Handling

This repository may integrate with Amazon Web Services services such as **Amazon Connect**, **Amazon Connect Customer Profiles**, and **Amazon Bedrock**.

### Do **not** commit credentials

Never commit any of the following to GitHub:

- AWS access keys (e.g., `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- AWS session credentials (e.g., `AWS_SESSION_TOKEN`)
- GitHub personal access tokens (PATs)
- SSH private keys, certificates, or keystores
- Any API keys, client secrets, or passwords

### How to provide credentials (use yours)

Use standard AWS SDK credential discovery:

- **Recommended (enterprise):** AWS IAM Identity Center (AWS SSO)
  - Configure locally: `aws configure sso`
  - Then run tools with: `AWS_PROFILE=<your-profile>`
- **Alternative:** AWS shared credentials file (`~/.aws/credentials`) and config (`~/.aws/config`)
- **CI/CD:** Use **GitHub Actions secrets** or (preferred) **OIDC** to assume an AWS IAM role

This codebase should read credentials from **environment variables** and/or your **AWS CLI profile**, never from hardcoded values.

### If credentials were ever committed

1. **Rotate/revoke** the credential immediately.
2. Remove it from the repository content.
3. If needed, rewrite Git history to purge the secret.

## Reporting

For security questions or incident response, contact the **Maximus Digital Transformation Office (DTO)**.
