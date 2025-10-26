import hashlib

def sha256_hash(val):
    if type(val) == str:
        return hashlib.sha256(val.encode("utf-8")).hexdigest()
    else:
        return hashlib.sha256(val).hexdigest()

# Alias for hash function to maintain compatibility
def hash(val):
    """Hash function that accepts both string and bytes input."""
    if isinstance(val, str):
        return hashlib.sha256(val.encode('utf-8')).hexdigest()
    else:
        return hashlib.sha256(val).hexdigest()