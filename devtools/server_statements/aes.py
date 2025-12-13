import json

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from orm import StatementUploads
from ssh import fetch_encrypted_file, load_master_key


def decrypt_statement(row: StatementUploads) -> tuple[bytes, dict]:
    """AES-GCM decrypt the selected statement."""
    master_key = load_master_key()
    ciphertext = fetch_encrypted_file(row.file_name)
    cipher = Cipher(
        algorithms.AES(master_key), modes.GCM(row.init_vector, row.auth_tag)
    )
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    metadata = {}
    if row.metadata_field:
        try:
            metadata = json.loads(row.metadata_field)
        except Exception:
            try:
                metadata = json.loads(row.metadata_field + '"}')
            except Exception:
                metadata = {}
    return plaintext, metadata
