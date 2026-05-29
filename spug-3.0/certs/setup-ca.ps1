# Private CA Setup Script for TDYW Production Environment (Windows)
# Run this on a Windows management server with OpenSSL installed

Write-Host "========================================" -ForegroundColor Green
Write-Host "   Setting up Private CA for TDYW" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green

$ErrorActionPreference = "Stop"

# Configuration
$certDir = "e:\TDYW\spug-3.0\certs"
$prodCertDir = "$certDir\prod"
$caDir = "$certDir\ca"
$domain = "tdyw.jc"
$ipAddr = "192.168.1.49"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Certificate Directory: $certDir"
Write-Host "  Domain: $domain"
Write-Host "  IP Address: $ipAddr`n"

# Create directories
New-Item -ItemType Directory -Force -Path $caDir | Out-Null
New-Item -ItemType Directory -Force -Path $prodCertDir | Out-Null

# Check if CA already exists
if ((Test-Path "$caDir\ca.key") -and (Test-Path "$caDir\ca.crt")) {
    Write-Host "CA already exists at $caDir" -ForegroundColor Yellow
    $regenerate = Read-Host "Do you want to regenerate the CA? This will require all clients to reinstall! (y/N)"
    if ($regenerate -ne "y" -and $regenerate -ne "Y") {
        Write-Host "Using existing CA...`n" -ForegroundColor Green
    } else {
        Write-Host "Regenerating CA...`n" -ForegroundColor Green
        Remove-Item "$caDir\ca.key" -Force -ErrorAction SilentlyContinue
        Remove-Item "$caDir\ca.crt" -Force -ErrorAction SilentlyContinue
    }
}

# Create Root CA (if not exists)
if (-not (Test-Path "$caDir\ca.key")) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Step 1: Creating Root CA" -ForegroundColor Cyan
    Write-Host "========================================`n"

    # Generate CA private key (4096 bits for security)
    Write-Host "Generating CA private key..." -ForegroundColor Yellow
    & "C:\Program Files\Git\usr\bin\openssl.exe" genrsa -out "$caDir\ca.key" 4096
    Write-Host "✓ CA private key created" -ForegroundColor Green

    # Generate CA certificate (10 years validity)
    Write-Host "Generating CA certificate..." -ForegroundColor Yellow
    & "C:\Program Files\Git\usr\bin\openssl.exe" req -new -x509 -days 3650 -key "$caDir\ca.key" -out "$caDir\ca.crt" `
        -subj "/C=CN/ST=Beijing/L=Beijing/O=YourCompany/OU=IT/CN=Spug-Root-CA"
    Write-Host "✓ CA certificate created (10 years validity)`n" -ForegroundColor Green
}

# Generate server certificate
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Step 2: Creating Server Certificate" -ForegroundColor Cyan
Write-Host "========================================`n"

# Remove old certificates
Remove-Item "$prodCertDir\spug.key" -Force -ErrorAction SilentlyContinue
Remove-Item "$prodCertDir\spug.csr" -Force -ErrorAction SilentlyContinue
Remove-Item "$prodCertDir\spug.crt" -Force -ErrorAction SilentlyContinue

# Generate server private key
Write-Host "Generating server private key..." -ForegroundColor Yellow
& "C:\Program Files\Git\usr\bin\openssl.exe" genrsa -out "$prodCertDir\spug.key" 2048
Write-Host "✓ Server private key created" -ForegroundColor Green

# Create certificate signing request
Write-Host "Creating certificate signing request..." -ForegroundColor Yellow
& "C:\Program Files\Git\usr\bin\openssl.exe" req -new -key "$prodCertDir\spug.key" -out "$prodCertDir\spug.csr" `
    -subj "/C=CN/ST=Beijing/L=Beijing/O=YourCompany/CN=$domain"
Write-Host "✓ CSR created`n" -ForegroundColor Green

# Create certificate extension configuration
$extConfig = @"
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = $domain
DNS.2 = tdyw
DNS.3 = tdyw.jc
DNS.4 = localhost
IP.1 = $ipAddr
IP.2 = 192.168.1.49
"@
$extConfig | Out-File -FilePath "$prodCertDir\cert.ext" -Encoding ASCII
Write-Host "✓ Certificate extension config created" -ForegroundColor Green

# Sign server certificate with CA
Write-Host "Signing server certificate with CA..." -ForegroundColor Yellow
& "C:\Program Files\Git\usr\bin\openssl.exe" x509 -req -in "$prodCertDir\spug.csr" `
    -CA "$caDir\ca.crt" -CAkey "$caDir\ca.key" `
    -CAcreateserial -out "$prodCertDir\spug.crt" `
    -days 3650 -extfile "$prodCertDir\cert.ext"
Write-Host "✓ Server certificate signed by CA (10 years validity)`n" -ForegroundColor Green

# Clean up
Remove-Item "$prodCertDir\spug.csr" -Force -ErrorAction SilentlyContinue
Remove-Item "$prodCertDir\cert.ext" -Force -ErrorAction SilentlyContinue
Write-Host "✓ Cleanup completed`n" -ForegroundColor Green

# Display certificate info
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Step 3: Certificate Information" -ForegroundColor Cyan
Write-Host "========================================`n"

Write-Host "CA Certificate:" -ForegroundColor Yellow
& "C:\Program Files\Git\usr\bin\openssl.exe" x509 -in "$caDir\ca.crt" -noout -subject -issuer -dates

Write-Host "`nServer Certificate:" -ForegroundColor Yellow
& "C:\Program Files\Git\usr\bin\openssl.exe" x509 -in "$prodCertDir\spug.crt" -noout -subject -issuer -dates

# Create distribution package
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Step 4: Creating Client Distribution Package" -ForegroundColor Cyan
Write-Host "========================================`n"

$distDir = "$certDir\client-dist"
Remove-Item -Recurse -Force $distDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

# Copy CA certificate
Copy-Item "$caDir\ca.crt" -Destination "$distDir\"
Write-Host "✓ CA certificate copied to distribution package" -ForegroundColor Green

# Create installation instructions
$readmeContent = @"
# TDYW Private CA - Client Installation Guide

## What is this?

This package contains the root certificate for TDYW internal CA.
By installing this certificate, your browser will trust all certificates
signed by this CA, including the TDYW server certificate.

## Files

- `ca.crt` - Root CA certificate (install this)
- `spug.crt` - Server certificate (for reference only)

## Installation Instructions

### Windows

#### Method 1: Automated Installer (Recommended)

1. Right-click on `install-ca.bat`
2. Select "Run as Administrator"
3. Follow the prompts
4. Restart your browser

#### Method 2: Manual Installation

1. Right-click on `ca.crt`
2. Select "Install Certificate"
3. Select "Local Machine"
4. Click "Next"
5. Choose "Place all certificates in the following store"
6. Click "Browse"
7. Select "Trusted Root Certification Authorities"
8. Click "OK" → "Next" → "Finish"
9. Click "OK" on the success message

### Linux (Ubuntu/Debian)

```bash
sudo cp ca.crt /usr/local/share/ca-certificates/spug-ca.crt
sudo update-ca-certificates
```

### Linux (CentOS/RHEL)

```bash
sudo cp ca.crt /etc/pki/ca-trust/source/anchors/spug-ca.crt
sudo update-ca-trust
```

### macOS

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt
```

### Firefox

Firefox uses its own certificate store:

1. Open Firefox
2. Go to Settings → Privacy & Security
3. Scroll to "Certificates"
4. Click "View Certificates"
5. Go to "Authorities" tab
6. Click "Import"
7. Select `ca.crt`
8. Check "Trust this CA to identify websites"
9. Click "OK"

## Verification

After installation, verify by visiting:
- https://tdyw.jc
- https://tdyw
- https://192.168.1.49

The browser should show a secure lock icon without warnings.

## Troubleshooting

### Certificate not trusted after installation

1. Clear browser cache
2. Restart browser
3. Try in Incognito/Private mode
4. On Windows, run `certmgr.msc` and verify certificate in "Trusted Root Certification Authorities"

### Still seeing warnings

Check certificate details:
- Subject: CN=tdyw.jc
- Issuer: CN=Spug-Root-CA
- NotAfter: should be in the future

### Windows Installer Failed

1. Make sure you ran as Administrator
2. Check User Account Control (UAC) settings
3. Try manual installation instead

## Contact

If you have issues, contact IT support.
"@
$readmeContent | Out-File -FilePath "$distDir\README.md" -Encoding UTF8
Write-Host "✓ Installation instructions created" -ForegroundColor Green

# Create Windows installer script
$installerScript = @"
@echo off
echo ========================================
echo   Installing TDYW Root CA Certificate
echo ========================================
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo This script requires administrator privileges.
    echo.
    echo Please right-click and run as Administrator.
    echo.
    pause
    exit /b 1
)

echo Installing certificate...
certutil -addstore "Root" ca.crt

if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   Certificate installed successfully!
    echo ========================================
    echo.
    echo Next steps:
    echo 1. Restart your browser
    echo 2. Visit https://192.168.1.49
    echo 3. Verify you see the secure lock icon
    echo.
    pause
) else (
    echo.
    echo ========================================
    echo   Failed to install certificate
    echo ========================================
    echo.
    echo Please try manual installation:
    echo 1. Right-click ca.crt
    echo 2. Install Certificate
    echo 3. Trusted Root Certification Authorities
    echo.
    pause
    exit /b 1
)
"@
$installerScript | Out-File -FilePath "$distDir\install-ca.bat" -Encoding ASCII
Write-Host "✓ Windows installer created" -ForegroundColor Green

# Create uninstall script
$uninstallScript = @"
@echo off
echo ========================================
echo   Uninstalling TDYW Root CA Certificate
echo ========================================
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo This script requires administrator privileges.
    echo.
    echo Please right-click and run as Administrator.
    echo.
    pause
    exit /b 1
)

echo Removing certificate...
certutil -delstore "Root" Spug-Root-CA

if %errorLevel% equ 0 (
    echo.
    echo ========================================
    echo   Certificate removed successfully!
    echo ========================================
    echo.
    echo Note: This will cause the TDYW site to show
    echo security warnings again.
    echo.
    pause
) else (
    echo.
    echo ========================================
    echo   Failed to remove certificate
    echo ========================================
    echo.
    echo It may not be installed, or was already removed.
    echo.
    pause
    exit /b 1
)
"@
$uninstallScript | Out-File -FilePath "$distDir\uninstall-ca.bat" -Encoding ASCII
Write-Host "✓ Windows uninstaller created" -ForegroundColor Green

Write-Host "`n✓ Client distribution package created at $distDir`n" -ForegroundColor Green

# Summary
Write-Host "========================================" -ForegroundColor Green
Write-Host "✅ Setup Complete!" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green

Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Deploy server certificate (already done)" -ForegroundColor White
Write-Host "2. Copy certs to production server:" -ForegroundColor White
Write-Host "   - ca\ca.crt → /opt/spug-3.0/certs/ca/" -ForegroundColor Gray
Write-Host "   - prod\spug.crt → /opt/spug-3.0/certs/prod/" -ForegroundColor Gray
Write-Host "   - prod\spug.key → /opt/spug-3.0/certs/prod/" -ForegroundColor Gray
Write-Host "`n3. Restart Docker containers on production:" -ForegroundColor White
Write-Host "   cd /opt/spug-3.0" -ForegroundColor Gray
Write-Host "   docker-compose -f docker-compose.prod.yml restart" -ForegroundColor Gray
Write-Host "`n4. Distribute CA certificate to clients:" -ForegroundColor White
Write-Host "   - Share folder: $distDir" -ForegroundColor Gray
Write-Host "   - Or ZIP the folder and send to users" -ForegroundColor Gray
Write-Host "`n5. Clients install CA certificate:" -ForegroundColor White
Write-Host "   - Windows: Right-click install-ca.bat → Run as Administrator" -ForegroundColor Gray
Write-Host "   - Other OS: Follow instructions in README.md" -ForegroundColor Gray
Write-Host "`n6. Verify installation:" -ForegroundColor White
Write-Host "   - Clients visit https://192.168.1.49" -ForegroundColor Gray
Write-Host "   - Browser should show secure lock icon`n" -ForegroundColor Gray

Write-Host "File Locations:" -ForegroundColor Yellow
Write-Host "  CA Certificate: $caDir\ca.crt" -ForegroundColor White
Write-Host "  Server Certificate: $prodCertDir\spug.crt" -ForegroundColor White
Write-Host "  Server Private Key: $prodCertDir\spug.key" -ForegroundColor White
Write-Host "  Client Package: $distDir\" -ForegroundColor White
Write-Host ""

Write-Host "✅ All done!" -ForegroundColor Green
Write-Host ""
