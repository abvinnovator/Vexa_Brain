"""
Test email address resolution — verifies all 3 layers:
  1. Direct regex match
  2. Speech reconstruction
  3. Contact fuzzy lookup
"""

import sys
sys.path.insert(0, ".")

from actions.email_action import EmailAction
from core.contacts import resolve_contact, load_contacts

contacts = load_contacts()
action = EmailAction(contacts=contacts)


print("=" * 60)
print("  Layer 1: Direct Regex Match")
print("=" * 60)

direct_tests = [
    ("send email to vamsi@gmail.com with subject test", "vamsi@gmail.com"),
    ("email to test.user@outlook.com subject hi", "test.user@outlook.com"),
]

passed = 0
failed = 0

for text, expected in direct_tests:
    result = action._resolve_address(text)
    status = "PASS" if result == expected else "FAIL"
    print(f"  {status}: '{text[:50]}...' -> {result}")
    if status == "PASS":
        passed += 1
    else:
        failed += 1


print(f"\n{'=' * 60}")
print("  Layer 2: Speech Reconstruction")
print("=" * 60)

speech_tests = [
    ("send email to vamsi at gmail dot com", "vamsi@gmail.com"),
    ("mail to brahma at the rate gmail dot com", "brahma@gmail.com"),
    ("email to john at sign outlook dot com", "john@outlook.com"),
    ("send mail to test at yahoo dot in", "test@yahoo.in"),
]

for text, expected in speech_tests:
    result = action._reconstruct_from_speech(text)
    status = "PASS" if result == expected else "FAIL"
    print(f"  {status}: '{text}' -> {result} (expected: {expected})")
    if status == "PASS":
        passed += 1
    else:
        failed += 1


print(f"\n{'=' * 60}")
print("  Layer 3: Contact Fuzzy Lookup")
print("=" * 60)

contact_tests = [
    # Exact match
    ("vamsi", "vamsiaratipamula@gmail.com"),
    ("brahma", "brahmavamsi1234@gmail.com"),
    # Case insensitive
    ("Vamsi", "vamsiaratipamula@gmail.com"),
    ("BRAHMA", "brahmavamsi1234@gmail.com"),
    # Fuzzy (typos Whisper might make)
    ("vampsi", "vamsiaratipamula@gmail.com"),
    ("vamsy", "vamsiaratipamula@gmail.com"),
    ("bramha", "brahmavamsi1234@gmail.com"),
    # No match
    ("unknown_person_xyz", None),
]

for name, expected in contact_tests:
    result = resolve_contact(name, contacts)
    status = "PASS" if result == expected else "FAIL"
    print(f"  {status}: '{name}' -> {result}")
    if status == "PASS":
        passed += 1
    else:
        failed += 1


print(f"\n{'=' * 60}")
print("  End-to-End: Full resolve_address (contact via 'send email to X')")
print("=" * 60)

e2e_tests = [
    # Contact name in speech — the main use case
    ("send email to vamsi with subject test and say hello", "vamsiaratipamula@gmail.com"),
    ("send an email to brahma subject hi say test", "brahmavamsi1234@gmail.com"),
    # Speech pattern
    ("send email to vamsi at gmail dot com with subject hi", "vamsi@gmail.com"),
    # Direct email
    ("send email to test@test.com subject hello", "test@test.com"),
]

for text, expected in e2e_tests:
    result = action._resolve_address(text)
    status = "PASS" if result == expected else "FAIL"
    print(f"  {status}: '{text[:55]}...' -> {result}")
    if status == "PASS":
        passed += 1
    else:
        failed += 1


print(f"\n{'=' * 60}")
print(f"  Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")
