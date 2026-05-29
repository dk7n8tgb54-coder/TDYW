#!/bin/bash
# Private CA Setup Script for Spug Production Environment
# This script creates a private CA and signs the server certificate
# Run this on the production Linux server

set -e

echo "========================================"
echo "   Setting up Private CA for Spug"
echo "========================================"
echo ""

# Configuration
CERT_DIR="/opt/spug-3.0/certs"
PROD_CERT_DIR="$CERT_DIR/prod"
CA_DIR="$CERT_DIR/ca"
DOMAIN=${1:-"tdyw.jc"}
IP_ADDR=${2:-"192.168.1.49"}

echo "Configuration:"
echo "  Certificate Directory: $CERT_DIR"
echo "  Domain: $DOMAIN"
echo "  IP Address: $IP_ADDR"
echo ""

# Create directories
mkdir -p "$CA_DIR"
mkdir -p "$PROD_CERT_DIR"

# Check if CA already exists
if [ -f "$CA_DIR/ca.key" ] && [ -f "$CA_DIR/ca.crt" ]; then
    echo "CA already exists at $CA_DIR"
    read -p "Do you want to regenerate the CA? This will require all clients to reinstall! (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Using existing CA..."
    else
        echo "Regenerating CA..."
        rm -f "$CA_DIR/ca.key" "$CA_DIR/ca.crt"
    fi
fi

# Create Root CA (if not exists)
if [ ! -f "$CA_DIR/ca.key" ]; then
    echo "========================================"
    echo "Step 1: Creating Root CA"
    echo "========================================"

    # Generate CA private key (4096 bits for security)
    openssl genrsa -out "$CA_DIR/ca.key" 4096
    echo "✓ CA private key created"

    # Generate CA certificate (10 years validity)
    openssl req -new -x509 -days 3650 -key "$CA_DIR/ca.key" -out "$CA_DIR/ca.crt" \
        -subj "/C=CN/ST=Beijing/L=Beijing/O=YourCompany/OU=IT/CN=Spug-Root-CA"
    echo "✓ CA certificate created (10 years validity)"

    # Set permissions
    chmod 600 "$CA_DIR/ca.key"
    chmod 644 "$CA_DIR/ca.crt"
    echo "✓ Permissions set"
    echo ""
fi

# Generate server certificate
echo "========================================"
echo "Step 2: Creating Server Certificate"
echo "========================================"

# Remove old certificates
rm -f "$PROD_CERT_DIR/spug.key" "$PROD_CERT_DIR/spug.csr" "$PROD_CERT_DIR/spug.crt"

# Generate server private key
openssl genrsa -out "$PROD_CERT_DIR/spug.key" 2048
echo "✓ Server private key created"

# Create certificate signing request
openssl req -new -key "$PROD_CERT_DIR/spug.key" -out "$PROD_CERT_DIR/spug.csr" \
    -subj "/C=CN/ST=Beijing/L=Beijing/O=YourCompany/CN=$DOMAIN"
echo "✓ CSR created"

# Create certificate extension configuration
cat > "$PROD_CERT_DIR/cert.ext" << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DOMAIN
DNS.2 = tdyw
DNS.3 = tdyw.jc
DNS.4 = localhost
IP.1 = $IP_ADDR
IP.2 = 192.168.1.49
EOF
echo "✓ Certificate extension config created"

# Sign server certificate with CA
openssl x509 -req -in "$PROD_CERT_DIR/spug.csr" \
    -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" \
    -CAcreateserial -out "$PROD_CERT_DIR/spug.crt" \
    -days 3650 -extfile "$PROD_CERT_DIR/cert.ext"
echo "✓ Server certificate signed by CA (10 years validity)"

# Clean up
rm -f "$PROD_CERT_DIR/spug.csr" "$PROD_CERT_DIR/cert.ext"
echo "✓ Cleanup completed"

# Set permissions
chmod 600 "$PROD_CERT_DIR/spug.key"
chmod 644 "$PROD_CERT_DIR/spug.crt"
echo "✓ Permissions set"
echo ""

# Display certificate info
echo "========================================"
echo "Step 3: Certificate Information"
echo "========================================"
echo ""
echo "CA Certificate:"
openssl x509 -in "$CA_DIR/ca.crt" -noout -subject -issuer -dates
echo ""
echo "Server Certificate:"
openssl x509 -in "$PROD_CERT_DIR/spug.crt" -noout -subject -issuer -dates
echo ""

# Create distribution package
echo "========================================"
echo "Step 4: Creating Client Distribution Package"
echo "========================================"
DIST_DIR="$CERT_DIR/client-dist"
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# Copy CA certificate and instructions
cp "$CA_DIR/ca.crt" "$DIST_DIR/"
cp "$PROD_CERT_DIR/spug.crt" "$DIST_DIR/"

# Create installation instructions
cat > "$DIST_DIR/README.md" << 'EOF'
# Spug Private CA - Client Installation Guide

## What is this?

This package contains the root certificate for the Spug internal CA.
By installing this certificate, your browser will trust all certificates
signed by this CA, including the Spug server certificate.

## Files

- `ca.crt` - Root CA certificate (install this)
- `spug.crt` - Server certificate (for reference only)

## Installation Instructions

### Windows

1. Right-click on `ca.crt`
2. Select "Install Certificate"
3. Select "Local Machine"
4. Choose "Place all certificates in the following store"
5. Browse to "Trusted Root Certification Authorities"
6. Click "Next" → "Finish"
7. Verify by opening https://tdyw.jc in your browser

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
- https://192.168.x.x (replace with actual IP)

The browser should show a secure lock icon without warnings.

## Troubleshooting

### Certificate not trusted after installation

1. Clear browser cache
2. Restart browser
3. Try in Incognito/Private mode
4. On Windows, run `certmgr.msc` and verify certificate in "Trusted Root Certification Authorities"

### Still seeing warnings

Check the certificate details:
- Subject: CN=tdyw.jc
- Issuer: CN=Spug-Root-CA
- NotAfter: should be in the future

## Contact

If you have issues, contact IT support.
EOF

# Create Windows installer script
cat > "$DIST_DIR\install-ca.bat" << 'EOF'
@echo off
echo Installing Spug Root CA Certificate...
echo.

REM Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo This script requires administrator privileges.
    echo Please right-click and run as Administrator.
    pause
    exit /b 1
)

REM Install certificate
certutil -addstore "Root" ca.crt

if %errorLevel% equ 0 (
    echo.
    echo Certificate installed successfully!
    echo Please restart your browser and visit https://tdyw.jc
    pause
) else (
    echo.
    echo Failed to install certificate.
    pause
    exit /b 1
)
EOF

echo "✓ Client distribution package created at $DIST_DIR"

# Create tarball for easy distribution
cd "$CERT_DIR"
tar -czf "spug-ca-client-install-$(date +%Y%m%d).tar.gz" -C client-dist .
echo "✓ Distribution package: spug-ca-client-install-$(date +%Y%m%d).tar.gz"

echo ""
echo "========================================"
echo "✅ Setup Complete!"
echo "========================================"
echo ""
echo "Next Steps:"
echo "1. Deploy the server certificate (already done)"
echo "2. Restart Docker containers:"
echo "   cd /opt/spug-3.0"
echo "   docker-compose -f docker-compose.prod.yml restart"
echo ""
echo "3. Distribute CA certificate to clients:"
echo "   - Share file: $DIST_DIR"
echo "   - Or share package: spug-ca-client-install-*.tar.gz"
echo ""
echo "4. Clients install the CA certificate:"
echo "   - Windows: Run install-ca.bat as Administrator"
echo "   - Linux: Follow instructions in README.md"
echo ""
echo "5. Verify installation:"
echo "   - Clients visit https://tdyw.jc"
echo "   - Browser should show secure lock icon"
echo ""
echo "CA Certificate Location: $CA_DIR/ca.crt"
echo "Server Certificate Location: $PROD_CERT_DIR/spug.crt"
echo ""
