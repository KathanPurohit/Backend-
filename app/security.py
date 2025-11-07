# app/security.py
from passlib.context import CryptContext
import hashlib

# Use bcrypt for hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class PasswordHasher:
    @staticmethod
    def _truncate_password(password: str) -> str:
        """
        Truncate or pre-hash the password if it's longer than bcrypt's max limit (72 bytes).
        """
        if len(password.encode('utf-8')) > 72:
            # Hash with SHA-256 and reduce to 64 hex chars
            return hashlib.sha256(password.encode("utf-8")).hexdigest()
        return password

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verifies a plain password against a hashed one."""
        plain_password = PasswordHasher._truncate_password(plain_password)
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        """Hashes a plain password, handling long passwords safely."""
        password = PasswordHasher._truncate_password(password)
        return pwd_context.hash(password)
