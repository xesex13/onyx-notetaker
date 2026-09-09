to find machine ids in powershell: python -c "import uuid, hashlib; print(hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:16])"
for people to download in powershell: iwr -useb https://raw.githubusercontent.com/xesex13/onyx-notetaker/main/install.ps1 | iex
for people to download in powershell: curl -fsSL https://raw.githubusercontent.com/xesex13/onyx-notetaker/main/install.sh | bash