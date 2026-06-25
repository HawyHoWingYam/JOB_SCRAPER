Add-Type -AssemblyName System.Web
$target = "https://index.docker.io/v1/access-token"

# Try using CredentialManager class
try {
    $cred = New-Object CredentialManagement.Credential
    $cred.Target = $target
    if ($cred.Load()) {
        Write-Host "ACCESS_TOKEN:$($cred.Password)"
    }
} catch {
    Write-Host "CredentialManagement not available"
}

# Alternative: use Windows.Security.Credentials
try {
    $vault = New-Object Windows.Security.Credentials.PasswordVault
    $creds = $vault.FindAllByResource($target)
    if ($creds.Count -gt 0) {
        $c = $creds[0]
        $c.RetrievePassword()
        Write-Host "VAULT_TOKEN:$($c.Password)"
    }
} catch {
    Write-Host "PasswordVault not available"
}
