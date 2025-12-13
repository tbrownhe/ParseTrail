import base64
import hashlib
from pathlib import Path


from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger

from parsetrail.core.settings import settings
from parsetrail.core.api import api_client


def cache_public_key(force: bool = False):
    """Downloads and caches the server's public RSA key

    Args:
        force (bool, optional): Force download of new key from server. Defaults to False.

    Raises:
        Exception: Unable to fetch key
    """
    # Return early if file is cached
    if settings.server_public_key.exists() and not force:
        return

    # Get the file from server
    logger.info("Downloading server public key")
    public_key_bytes = api_client.get_public_key()
    with settings.server_public_key.open("wb") as key_file:
        key_file.write(public_key_bytes)


def validate_public_key():
    """Makes sure that locally cached server public key matches the remote copy,
    then returns the validated key for use.

    Raises:
        ValueError: Could not validate server's public key

    Returns:
        PublicKeyTypes: PublicKey of server
    """
    try:
        # Make sure a public key is cached
        cache_public_key()
        public_key_hash_server = api_client.get_public_key_hash()
        logger.info("Validating server public key hash")

        with settings.server_public_key.open("rb") as key_file:
            public_key_bytes = key_file.read()

        public_key_hash_local = hashlib.sha256(public_key_bytes).hexdigest()
        if public_key_hash_local != public_key_hash_server:
            raise ValueError("Public key verification failed. Hash mismatch.")
        return serialization.load_pem_public_key(public_key_bytes)
    except Exception as e:
        logger.error(f"Error during public key verification: {e}")
        raise


def encrypt_symmetric_key(_symmetric_key: bytes) -> str:
    """Encrypt the symmetric key using the server's public RSA key.
    High security encryption for very small amounts of data.
    Using RSA to encrypt the symmetric key provides the same level of security
    as directly encrypting the file. The symmetric key is inaccessible without
    the server's private RSA key.

    Args:
        symmetric_key (bytes): Fernet key for decrypting file

    Returns:
        bytes: Fernet key encrypted using server's RSA key
    """
    logger.info("Encrypting symmetric key with server public key")
    try:
        public_key = validate_public_key()
    except ValueError:
        logger.debug("Refreshing locally cached server public key")
        cache_public_key(force=True)
        public_key = validate_public_key()

    encrypted_key = public_key.encrypt(
        _symmetric_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted_key).decode("utf-8")


def encrypt_file(fpath: Path) -> tuple[bytes, bytes]:
    """Encrypt each file with a unique symmetric key.

    Args:
        fpath (Path): File to be encrypted

    Returns:
        tuple[bytes, bytes]: Encrypted data, Encrypted key
    """
    logger.info("Encrypting file with new symmetric key")
    _key = Fernet.generate_key()
    cipher = Fernet(_key)
    with fpath.open("rb") as f:
        encrypted_file = cipher.encrypt(f.read())
    encrypted_key = encrypt_symmetric_key(_key)
    return encrypted_file, encrypted_key
