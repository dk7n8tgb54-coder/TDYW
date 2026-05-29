# Project Configuration

This directory contains configuration files for different environments.

## Directory Structure

```
config/
├── dev/              # Development environment config
│   └── nginx.conf    # Development Nginx config
└── prod/             # Production environment config
    └── nginx.conf    # Production Nginx config
```

## Usage

### Development
```powershell
docker-compose up -d
```

### Production
```powershell
docker-compose -f docker-compose.prod.yml up -d
```

## Environment Files

- `.env` - Common environment variables
- `.env.dev` - Development specific variables
- `.env.prod` - Production specific variables
