# TDYW Private CA - Client Installation Guide

## What is this?

This package contains the root certificate for TDYW internal CA.
By installing this certificate, your browser will trust all certificates
signed by this CA, including the TDYW server certificate.

## Files

- ca.crt - Root CA certificate (install this)
- spug.crt - Server certificate (for reference only)

## Installation Instructions

### Windows

#### Method 1: Automated Installer (Recommended)

1. Right-click on install-ca.bat
2. Select "Run as Administrator"
3. Follow the prompts
4. Restart your browser

#### Method 2: Manual Installation

1. Right-click on ca.crt
2. Select "Install Certificate"
3. Select "Local Machine"
4. Click "Next"
5. Choose "Place all certificates in the following store"
6. Click "Browse"
7. Select "Trusted Root Certification Authorities"
8. Click "OK" 鈫?"Next" 鈫?"Finish"
9. Click "OK" on the success message

### Linux (Ubuntu/Debian)

`ash
sudo cp ca.crt /usr/local/share/ca-certificates/spug-ca.crt
sudo update-ca-certificates
`

### Linux (CentOS/RHEL)

`ash
sudo cp ca.crt /etc/pki/ca-trust/source/anchors/spug-ca.crt
sudo update-ca-trust
`

### macOS

`ash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt
`

### Firefox

Firefox uses its own certificate store:

1. Open Firefox
2. Go to Settings 鈫?Privacy & Security
3. Scroll to "Certificates"
4. Click "View Certificates"
5. Go to "Authorities" tab
6. Click "Import"
7. Select ca.crt
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
4. On Windows, run certmgr.msc and verify certificate in "Trusted Root Certification Authorities"

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
