# app/security.py

from passlib.context import CryptContext
import hashlib

# Configure the password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class PasswordHasher:
    @staticmethod
    def _truncate_password(password: str) -> str:
        """
        Truncate or pre-hash the password if it exceeds bcrypt's 72-byte limit.
        Bcrypt only supports passwords up to 72 bytes, so for longer passwords,
        we hash them using SHA-256 first to produce a fixed-length string.
        """
        if len(password.encode('utf-8')) > 72:
            # Hash with SHA-256 and return the 64-character hex digest
            return hashlib.sha256(password.encode("utf-8")).hexdigest()
        return password

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain password against its hashed version.
        Automatically handles long passwords by safely truncating if needed.
        """
        plain_password = PasswordHasher._truncate_password(plain_password)
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        """
        Hash a plain password securely. If the password is longer than bcrypt's limit,
        we pre-hash it using SHA-256 first.
        """
        password = PasswordHasher._truncate_password(password)
        return pwd_context.hash(password)
