import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Llave simétrica de 256 bits (32 bytes). Si no existe en .env, genera una temporal para dev
RAW_KEY = os.getenv("RECORDING_AES_KEY", "0123456789abcdef0123456789abcdef")
KEY = RAW_KEY.encode("utf-8")[:32]

def encrypt_file_data(data: bytes) -> bytes:
    """Cifra los bytes usando AES-GCM adjuntando el nonce de 12 bytes al inicio."""
    aesgcm = AESGCM(KEY)
    nonce = os.urandom(12)
    encrypted = aesgcm.encrypt(nonce, data, None)
    return nonce + encrypted

def decrypt_file_data(encrypted_data: bytes) -> bytes:
    """Extrae el nonce de los primeros 12 bytes y descifra el contenido."""
    aesgcm = AESGCM(KEY)
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)