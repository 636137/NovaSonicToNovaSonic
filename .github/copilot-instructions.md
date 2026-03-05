# Amazon Connect + Lex Project Guidelines

## Overview

Custom instructions for this Amazon Connect contact center project with Lex bots, Lambda functions, and voice testing capabilities. These instructions define coding standards and guidelines that apply to all work in this repository.

For specialized workflows, use the available **Agent Skills** (type `/` in chat to see them):

| Skill | Purpose |
|-------|---------|
| `/aws-deployment` | Deploy AWS infrastructure with error handling and self-healing |
| `/nova-sonic` | Deploy Nova Sonic bidirectional voice streaming applications |
| `/voice-testing` | Create and execute real voice call tests |
| `/testing-automation` | Generate and run automated tests |

## Project Structure

```
├── .github/
│   ├── copilot-instructions.md  # These instructions
│   └── skills/                  # Agent Skills (portable, auto-loaded)
├── cdk/                         # CDK infrastructure stacks
├── contact_flows/               # Amazon Connect contact flow JSON
├── docs/                        # Additional documentation
├── lambda/                      # Lambda function handlers
├── lex/                         # Lex bot definitions
├── scripts/                     # Deployment and utility scripts
└── voice_tester/                # Voice testing framework
```

## Coding Standards

### Python
- Use type hints for all functions
- Follow PEP 8 style guide
- Docstrings for public functions (Google style)
- Use `logging` module, not `print()` in Lambda
- Prefer `pathlib` over `os.path`

### AWS CDK
- Use TypeScript or Python for CDK
- Tag all resources with `project`, `environment`, `owner`
- Enable deletion protection for stateful resources
- Use CDK context for configuration, not hardcoded values

### Lambda Functions
- Keep handlers thin - delegate to utility modules
- Set appropriate timeouts (default 30s is often too long)
- Use environment variables for configuration
- Include structured JSON logging

### Lex V2
- Use PascalCase for enum values (e.g., "TopResolution")
- Handle `ConflictException` for resource conflicts
- Always wait for bot to reach "Available" state before building
- Create slot types before intents that reference them

## Security Requirements

- Store credentials in `.env` files (gitignored)
- Use IAM roles over access keys where possible
- Enable encryption at rest for all data stores
- Follow least-privilege principle for IAM policies
- Never log sensitive data (PII, credentials)

## Error Handling Patterns

### AWS Operations
```python
import time
from botocore.exceptions import ClientError

def wait_for_resource(check_fn, target_state, max_wait=300):
    """Wait with exponential backoff."""
    wait_time = 5
    total = 0
    while total < max_wait:
        if check_fn() == target_state:
            return True
        time.sleep(wait_time)
        total += wait_time
        wait_time = min(wait_time * 1.5, 30)
    raise TimeoutError(f"Resource did not reach {target_state}")
```

### Lambda Error Response
```python
def error_response(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message}),
        "headers": {"Content-Type": "application/json"}
    }
```

## Testing Requirements

- Unit tests required for Lambda handlers
- Integration tests for AWS resource interactions
- Contact flow validation before deployment
- Use `pytest` with coverage reporting
- Mock AWS services with `moto` for unit tests

## Documentation Guidelines

- README.md for each major component
- Inline comments for complex logic
- Include example invocations in Lambda README
- Document all environment variables

## Behavior Guidelines

### Do:
- Check prerequisites before starting deployments
- Provide progress updates frequently
- Test after each deployment step
- Handle errors gracefully with recovery
- Tag all AWS resources
- Estimate costs before creating resources

### Don't:
- Assume tools are installed
- Skip error handling
- Deploy without testing
- Hardcode credentials or ARNs
- Create resources without tags
- Leave orphaned resources on failure

---

**Version**: 2.0.0
**Last Updated**: March 4, 2026
