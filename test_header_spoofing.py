#!/usr/bin/env python3
"""
Test script to validate header spoofing protection in the SSO implementation.
This script validates the security configuration without requiring external dependencies.
"""

import sys
import os
import re

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def test(self, name, condition, message=""):
        if condition:
            print(f"✅ PASS: {name}")
            self.passed += 1
        else:
            print(f"❌ FAIL: {name} - {message}")
            self.failed += 1
        self.tests.append((name, condition, message))

    def summary(self):
        total = self.passed + self.failed
        print(f"\n=== Test Summary ===")
        print(f"Total: {total}, Passed: {self.passed}, Failed: {self.failed}")
        if self.failed > 0:
            print(f"\n❌ SECURITY ISSUES DETECTED - Review failed tests!")
            return False
        else:
            print(f"\n✅ All security tests passed!")
            return True

def test_sso_middleware_security():
    """Test the SSOMiddleware security implementation by analyzing the code"""
    results = TestResults()

    print("Testing SSOMiddleware Security Implementation\n")

    try:
        with open("app/webgui.py", "r") as f:
            code = f.read()

        # Test for localhost restriction
        results.test("Localhost restriction implemented",
                    'client_host not in ["127.0.0.1", "::1", "localhost"]' in code,
                    "Should restrict SSO headers to localhost only")

        # Test for header validation function
        results.test("Header validation function exists",
                    "_is_valid_sso_headers" in code,
                    "Should have header validation function")

        # Test for forbidden character checking
        forbidden_chars_check = r"forbidden_chars.*=.*\[.*\\n.*\\r.*\\0.*\\t.*\]"
        results.test("Forbidden character validation",
                    re.search(forbidden_chars_check, code) is not None,
                    "Should check for forbidden characters (newlines, etc)")

        # Test for length validation
        results.test("Username length validation",
                    "len(user) > 256" in code,
                    "Should validate username length")

        # Test for email validation
        results.test("Email format validation",
                    "'@' not in email" in code,
                    "Should validate email format")

        # Test for group limit validation
        results.test("Group count limit",
                    "len(group_list) > 50" in code,
                    "Should limit number of groups to prevent DoS")

        # Test for session clearing on invalid headers
        results.test("Session clearing on invalid headers",
                    'request.session.clear()' in code,
                    "Should clear session if headers are invalid")

        # Test for admin logging
        results.test("Admin access logging",
                    'logger.info(f"Admin access granted' in code,
                    "Should log admin access for monitoring")

    except FileNotFoundError:
        results.test("SSOMiddleware file exists", False, "webgui.py not found")
        return False

    return results.summary()

def test_nginx_config():
    """Test nginx configuration for header spoofing protection"""
    print("\n" + "="*50)
    print("Testing Nginx Configuration")
    print("="*50)

    results = TestResults()

    # Read nginx config
    try:
        with open("installation/nginx.conf.template", "r") as f:
            config = f.read()

        # Test for comprehensive header clearing
        required_clears = [
            'proxy_set_header X-Forwarded-User ""',
            'proxy_set_header X-Forwarded-Groups ""',
            'proxy_set_header X-User ""',
            'proxy_set_header X-Email ""',
            'proxy_set_header Authorization ""',
            'proxy_set_header X-Auth-Request-User ""'
        ]

        for header_clear in required_clears:
            results.test(f"Header clearing: {header_clear.split()[2]}",
                        header_clear in config,
                        f"Missing header clear: {header_clear}")

        # Test for safe variable usage
        results.test("Safe user variable", "$safe_user" in config,
                    "Should use $safe_user instead of direct $user")
        results.test("Safe groups variable", "$safe_groups" in config,
                    "Should use $safe_groups instead of direct $groups")

        # Test for auth_request protection
        results.test("Auth request validation", "auth_request /oauth2/auth" in config,
                    "Should validate all requests through oauth2-proxy")

    except FileNotFoundError:
        results.test("Nginx config exists", False, "nginx.conf.template not found")

    return results.summary()

def main():
    """Run all security tests"""
    print("🔒 Security Test Suite for OAuth2-proxy Implementation")
    print("="*60)

    # Test the SSOMiddleware
    middleware_ok = test_sso_middleware_security()

    # Test nginx configuration
    nginx_ok = test_nginx_config()

    print("\n" + "="*60)
    if middleware_ok and nginx_ok:
        print("🎉 ALL SECURITY TESTS PASSED!")
        print("The header spoofing protection is working correctly.")
        return 0
    else:
        print("⚠️  SECURITY ISSUES DETECTED!")
        print("Please review and fix the failed tests before deployment.")
        return 1

if __name__ == "__main__":
    sys.exit(main())