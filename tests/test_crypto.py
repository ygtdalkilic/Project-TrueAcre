import base64

import pytest
from cryptography.exceptions import InvalidTag

from api import crypto


def test_round_trip_and_fresh_nonces():
    text = "grower_id,name\nG1,Ann Farmer\n"
    a, b = crypto.encrypt(text), crypto.encrypt(text)
    assert crypto.decrypt(a) == text and crypto.decrypt(b) == text
    assert a != b  # a new nonce every time, so equal inputs never produce equal ciphertexts
    assert b"Ann Farmer" not in a


def test_tampering_is_detected():
    blob = bytearray(crypto.encrypt("secret rows"))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        crypto.decrypt(bytes(blob))


def test_generated_keys_are_32_random_bytes():
    key = crypto.generate_key()
    assert len(base64.urlsafe_b64decode(key)) == 32
    assert key != crypto.generate_key()
