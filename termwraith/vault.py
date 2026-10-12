import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .store import CONFIG_FILE

VAULT_FILE = CONFIG_FILE.parent / "vault.json"


class VaultError(Exception):
    pass


def _fernet(master: str, salt: bytes) -> Fernet:
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(master.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def load_passwords(master: str) -> dict[str, str]:
    if not VAULT_FILE.exists():
        return {}
    data = json.loads(VAULT_FILE.read_text())
    try:
        raw = _fernet(master, base64.b64decode(data["salt"])).decrypt(data["token"].encode())
    except InvalidToken as exc:
        raise VaultError("wrong master password") from exc
    return json.loads(raw)


def save_passwords(passwords: dict[str, str], master: str) -> None:
    salt = os.urandom(16)
    token = _fernet(master, salt).encrypt(json.dumps(passwords).encode()).decode()
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_FILE.write_text(json.dumps({"salt": base64.b64encode(salt).decode(), "token": token}) + "\n")
    VAULT_FILE.chmod(0o600)


def _script_key(name: str) -> str:
    return f"script:{name}"


def load_script(master: str, name: str) -> list[str]:
    text = load_passwords(master).get(_script_key(name), "")
    return text.splitlines()


def set_script(master: str, name: str, lines: list[str], old_name: str | None = None) -> None:
    passwords = load_passwords(master)
    if old_name is not None:
        passwords.pop(_script_key(old_name), None)
    if lines:
        passwords[_script_key(name)] = "\n".join(lines)
    else:
        passwords.pop(_script_key(name), None)
    save_passwords(passwords, master)
