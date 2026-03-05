# Copilot Agent Skills

This document explains how to use and customize the Agent Skills included in this project. Copy these skills to any project to enable AI-powered workflows in GitHub Copilot.

## What Are Agent Skills?

Agent Skills are portable knowledge modules that give GitHub Copilot domain-specific expertise. When you invoke a skill (via `/skill-name` or by asking relevant questions), Copilot loads the skill's instructions and uses them to provide better responses.

**Benefits:**
- Consistent behavior across team members
- Domain-specific knowledge without re-explaining
- Reusable across multiple projects
- Version controlled with your code

## Quick Start

### Copy Skills to Your Project

```bash
# From this repo, copy to your project
cp -r .github/skills/ /path/to/your/project/.github/skills/
cp .github/copilot-instructions.md /path/to/your/project/.github/
```

### Use in Copilot Chat

1. Open Copilot Chat in VS Code
2. Type `/` to see available skills
3. Select a skill or ask a question - Copilot auto-detects relevant skills

---

## Available Skills

### 1. AWS Deployment (`/aws-deployment`)

**Purpose:** Deploy AWS infrastructure with Amazon Connect, Lex, Lambda, and other services.

**Use Cases:**
- Deploy new Connect instances
- Create Lex bots and intents
- Set up Lambda functions
- Configure IAM roles and policies

**Key Features:**
- Idempotent operations (safe to re-run)
- Self-healing error recovery
- Resource tagging standards
- Security best practices

**Example Invocation:**
```
/aws-deployment Deploy a Lex bot for customer service with FAQ intent
```

**Location:** `.github/skills/aws-deployment/`

---

### 2. Nova Sonic (`/nova-sonic`)

**Purpose:** Build bidirectional voice streaming applications with Amazon Nova Sonic.

**Use Cases:**
- Create AI voice agents
- Build AI-to-AI conversations
- Real-time audio processing
- Voice bot development

**Key Features:**
- Audio format specifications
- Turn-taking with VAD
- Voice configuration
- Troubleshooting patterns

**Example Invocation:**
```
/nova-sonic Create a customer service voice bot with Nova Sonic
```

**Location:** `.github/skills/nova-sonic/`

---

### 3. Voice Testing (`/voice-testing`)

**Purpose:** Create and execute real voice call tests against Amazon Connect.

**Use Cases:**
- Test IVR contact flows
- Validate Lex bot conversations
- Regression testing
- Load testing with concurrent calls

**Key Features:**
- YAML test scenario format
- PSTN call execution
- Status tracking
- Result evaluation

**Example Invocation:**
```
/voice-testing Create a test for the main menu IVR flow
```

**Location:** `.github/skills/voice-testing/`

---

### 4. Testing Automation (`/testing-automation`)

**Purpose:** Generate and execute automated tests for AWS infrastructure.

**Use Cases:**
- Unit tests for Lambda handlers
- Integration tests for Lex bots
- E2E contact flow validation
- Mock AWS services with moto

**Key Features:**
- pytest patterns
- AWS service mocking
- Coverage reporting
- CI/CD integration

**Example Invocation:**
```
/testing-automation Generate unit tests for the survey Lambda handler
```

**Location:** `.github/skills/testing-automation/`

---

## Skill File Structure

Each skill follows this structure:

```
.github/skills/
└── skill-name/
    ├── SKILL.md           # Main skill definition (required)
    ├── examples/          # Code examples (optional)
    │   └── example.py
    └── templates/         # Reusable templates (optional)
        └── template.json
```

### SKILL.md Format

```yaml
---
name: skill-name
description: Brief description (shown in skill picker)
argument-hint: "[optional] [arguments]"
user-invocable: true
disable-model-invocation: false
---

# Skill Title

Detailed instructions in Markdown format.

## When to Use

- Scenario 1
- Scenario 2

## Commands

### Command 1
Description and usage.

### Command 2
Description and usage.

## Examples

```python
# Code example
```

## Troubleshooting

Common issues and solutions.
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique skill identifier |
| `description` | Yes | Brief description shown in UI |
| `argument-hint` | No | Help text for arguments |
| `user-invocable` | Yes | Whether users can invoke directly |
| `disable-model-invocation` | No | Prevent auto-invocation |

---

## Customizing Skills

### Adding New Skills

1. Create folder: `.github/skills/my-skill/`
2. Create `SKILL.md` with frontmatter
3. Add content, examples, templates
4. Test in Copilot Chat

### Modifying Existing Skills

Edit the `SKILL.md` file to:
- Add new commands
- Update examples
- Include project-specific patterns
- Add troubleshooting tips

### Skill Best Practices

1. **Keep descriptions concise** - UI truncates long text
2. **Include concrete examples** - Copilot learns from examples
3. **Document edge cases** - Include troubleshooting sections
4. **Use consistent formatting** - Markdown tables work well
5. **Version your skills** - Track changes in git

---

## Project Instructions

The `.github/copilot-instructions.md` file provides project-wide instructions that apply to all Copilot interactions.

### What to Include

```markdown
# Project Guidelines

## Overview
Brief description of the project.

## Available Skills
List skills with their purposes.

## Coding Standards
- Language-specific guidelines
- Naming conventions
- Documentation requirements

## Architecture
Key patterns and structures.

## Security
Important security considerations.
```

### Example

See `.github/copilot-instructions.md` in this repo for a complete example.

---

## Troubleshooting

### Skills Not Appearing

1. Check file location: `.github/skills/name/SKILL.md`
2. Verify YAML frontmatter syntax
3. Ensure `user-invocable: true`
4. Restart VS Code

### Skill Not Auto-Detecting

1. Add more keywords to description
2. Include relevant terms in skill content
3. Use `disable-model-invocation: false`

### Skill Behavior Incorrect

1. Check examples in SKILL.md
2. Add more specific instructions
3. Include edge case handling

---

## Resources

- [VS Code Agent Skills Spec](https://agentskills.io)
- [GitHub Copilot Documentation](https://docs.github.com/copilot)
- [Amazon Connect Documentation](https://docs.aws.amazon.com/connect/)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
