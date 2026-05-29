# Production SSL Certificates

This directory contains SSL certificates for production environment.

## Files

- `spug.crt` - SSL certificate (must be provided)
- `spug.key` - SSL private key (must be provided)

## Certificate Options

### Option 1: Self-Signed Certificate (Testing Only)

Generate self-signed certificate:
```powershell
cd E:\TDYW\spug-3.0\certs
.\generate-cert.ps1
copy spug.crt prod\
copy spug.key prod\
```

**Note**: Browser will show security warning. OK for testing.

### Option 2: Let's Encrypt Certificate (Recommended)

1. Install Certbot:
```bash
sudo apt-get install certbot
```

2. Get certificate:
```bash
sudo certbot certonly --standalone -d your-domain.com
```

3. Copy certificates:
```bash
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem prod/spug.crt
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem prod/spug.key
```

### Option 3: CA Signed Certificate

Use certificates from a trusted CA (e.g.,阿里云,腾讯云).

## Deploy Certificates

```powershell
cd E:\TDYW\spug-3.0\certs
.\setup-cert-prod.bat
```

## Security

- Keep private key (spug.key) secure
- Never commit private key to version control
- Use strong passwords for certificate generation
