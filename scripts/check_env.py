#!/usr/bin/env python3
"""
Pre-flight environment variable checker.
Run before starting any REGX service to confirm required secrets are present.
"""

import sys
import os

REQUIRED = [
    "DJANGO_SECRET_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "MFA_ENCRYPTION_KEY",
]

PROHIBITED_VALUES = {
    "DJANGO_SECRET_KEY": ["change-me", "insecure", "secret", "example"],
    "MFA_ENCRYPTION_KEY": ["change-me"],
}


def main():
    missing = []
    insecure = []

    for var in REQUIRED:
        value = os.environ.get(var, "").strip()
        if not value:
            missing.append(var)
            continue
        for bad in PROHIBITED_VALUES.get(var, []):
            if bad.lower() in value.lower():
                insecure.append(f"{var} contains placeholder value '{bad}'")

    if missing:
        print(f"FAIL: Missing required env vars: {', '.join(missing)}", file=sys.stderr)
    if insecure:
        for msg in insecure:
            print(f"FAIL: {msg}", file=sys.stderr)

    if missing or insecure:
        sys.exit(1)

    print("OK: All required environment variables are present.")


if __name__ == "__main__":
    main()
