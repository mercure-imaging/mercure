# Microsoft Entra ID SSO Integration Setup

This guide walks you through setting up Single Sign-On (SSO) with Microsoft Entra ID (Azure AD) for Mercure.

## Prerequisites

1. Access to Microsoft Azure AD with app registration permissions
2. Docker and docker-compose installed
3. Mercure Docker setup already working

## Azure AD Configuration

### 1. Create App Registration

1. Go to Azure Portal → Azure Active Directory → App registrations
2. Click "New registration"
3. Set the following:
   - **Name**: `Mercure SSO`
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: `http://your-mercure-domain:8000/oauth2/callback`

### 2. Configure Authentication

1. In your app registration, go to **Authentication**
2. Add platform → Web
3. Add redirect URL: `http://your-mercure-domain:8000/oauth2/callback`
4. Enable **ID tokens** and **Access tokens**

### 3. Get Required Values

From your app registration overview page, note:
- **Application (client) ID**
- **Directory (tenant) ID**

### 4. Create Client Secret

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Set description and expiration
4. Copy the **Value** (not the Secret ID)

### 5. Configure Groups (Optional)

If you want to use Azure AD groups for admin access:
1. Create security groups in Azure AD (e.g., `mercure-admins`)
2. Add users to appropriate groups

## Mercure Configuration

### 1. Copy OAuth2 Configuration Template

```bash
cp docker/oauth2.env.template /opt/mercure/config/oauth2.env
```

### 2. Configure OAuth2 Settings

Edit `/opt/mercure/config/oauth2.env`:

```env
OAUTH2_PROXY_AZURE_TENANT=your-tenant-id-here
OAUTH2_PROXY_CLIENT_ID=your-client-id-here  
OAUTH2_PROXY_CLIENT_SECRET=your-client-secret-here
OAUTH2_PROXY_REDIRECT_URL=http://your-domain:8000/oauth2/callback
OAUTH2_PROXY_COOKIE_SECRET=generate-32-char-random-string
OAUTH2_PROXY_COOKIE_DOMAIN=your-domain
OAUTH2_ADMIN_GROUPS=mercure-admins,IT-Administrators
```

### 3. Generate Cookie Secret

Generate a 32-character random string for `OAUTH2_PROXY_COOKIE_SECRET`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

### 4. Start Services

```bash
cd docker
docker-compose up -d
```

## How It Works

1. **nginx** receives all requests on port 8000
2. **oauth2-proxy** handles Microsoft Entra ID authentication
3. For authenticated users, nginx forwards requests to **mercure-ui** with user headers
4. **SSOMiddleware** in mercure reads the headers and auto-provisions sessions
5. **SessionAuthBackend** works normally with provisioned sessions

## User Access

- **Regular users**: Any user in your Azure AD tenant can log in
- **Admin users**: Users in groups specified in `OAUTH2_ADMIN_GROUPS`
- **Fallback**: Traditional login at `/login` still works for emergency access

## Troubleshooting

### Check OAuth2 Proxy Logs
```bash
docker-compose logs oauth2-proxy
```

### Check Nginx Logs  
```bash
docker-compose logs nginx
```

### Check if Headers are Being Passed
Look for `X-Forwarded-User` headers in mercure UI logs.

### Common Issues

1. **Redirect URI mismatch**: Ensure Azure AD redirect URI exactly matches `OAUTH2_PROXY_REDIRECT_URL`
2. **Cookie domain issues**: Make sure `OAUTH2_PROXY_COOKIE_DOMAIN` matches your hostname
3. **Groups not working**: Verify Azure AD groups exist and users are members

## Security Notes

- Always use HTTPS in production
- Keep client secrets secure
- Regularly rotate client secrets
- Review user permissions periodically
- Consider using Azure AD Conditional Access for additional security