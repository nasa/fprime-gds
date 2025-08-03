# Base URL Configuration for F´ GDS

The F´ Ground Data System (GDS) now supports configurable base URLs, allowing you to run the GDS behind reverse proxies or at custom URL paths. This feature is particularly useful for:

- Running multiple GDS instances on the same server
- Deploying GDS behind reverse proxies (like nginx or Apache)
- Integrating GDS into existing web applications
- CI/CD pipelines and containerized deployments

## Quick Start

To run the GDS with a custom base URL, use the `--base-url` option:

```bash
fprime-gds --base-url /fprime-gds-2
```

This will make the GDS accessible at `http://localhost:5000/fprime-gds-2/` instead of the default `http://localhost:5000/`.

## Command Line Usage

### Basic Usage

```bash
# Run GDS at a custom path
fprime-gds --base-url /my-gds

# Run GDS with multi-level path
fprime-gds --base-url /projects/mission-1/gds

# Run GDS at root (default behavior)
fprime-gds --base-url ""
# or simply
fprime-gds
```

### Combined with Other Options

```bash
# Custom base URL with specific port and address
fprime-gds --base-url /fprime-gds --gui-addr 0.0.0.0 --gui-port 8080

# Custom base URL with deployment directory
fprime-gds --base-url /mission-gds -d /path/to/deployment
```

## Reverse Proxy Configuration

### Nginx Configuration

Here's an example nginx configuration to proxy the GDS:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /fprime-gds/ {
        proxy_pass http://127.0.0.1:5000/fprime-gds/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if needed for future features)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Start the GDS with:
```bash
fprime-gds --base-url /fprime-gds --gui-addr 127.0.0.1
```

### Apache Configuration

For Apache with mod_proxy:

```apache
<VirtualHost *:80>
    ServerName your-domain.com
    
    ProxyPreserveHost On
    ProxyPass /fprime-gds/ http://127.0.0.1:5000/fprime-gds/
    ProxyPassReverse /fprime-gds/ http://127.0.0.1:5000/fprime-gds/
</VirtualHost>
```

## Environment Variable Configuration

You can also set the base URL using environment variables:

```bash
export BASE_URL="/fprime-gds"
fprime-gds
```

This is useful for containerized deployments or when using configuration management tools.

## Docker Example

Here's a Docker Compose example running multiple GDS instances:

```yaml
version: '3.8'
services:
  gds-mission-1:
    image: fprime-gds:latest
    environment:
      - BASE_URL=/mission-1
    ports:
      - "5001:5000"
    command: fprime-gds --base-url /mission-1 --gui-addr 0.0.0.0

  gds-mission-2:
    image: fprime-gds:latest
    environment:
      - BASE_URL=/mission-2
    ports:
      - "5002:5000"
    command: fprime-gds --base-url /mission-2 --gui-addr 0.0.0.0

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - gds-mission-1
      - gds-mission-2
```

## URL Path Validation

The base URL must follow these rules:

- Must start with `/` (will be automatically added if missing)
- Cannot end with `/` (will be automatically removed, except for root `/`)
- Can only contain valid URL path characters: `a-z`, `A-Z`, `0-9`, `-`, `.`, `_`, `~`, `!`, `$`, `&`, `'`, `(`, `)`, `*`, `+`, `,`, `;`, `=`, `:`, `@`, `/`
- Cannot contain spaces or other invalid characters

### Valid Examples
- `/fprime-gds`
- `/projects/mission-1/gds`
- `/gds_v2.0`
- `/app-name`

### Invalid Examples
- `/fprime gds` (contains space)
- `/fprime<gds>` (contains invalid characters)

## Limitations and Considerations

1. **Static File Serving**: All static files (CSS, JavaScript, images) are automatically served with the correct base URL prefix.

2. **API Endpoints**: All REST API endpoints are automatically prefixed with the base URL.

3. **Browser Compatibility**: The feature works with all modern browsers. JavaScript dynamically constructs URLs based on the configured base URL.

4. **WebSocket Support**: If future versions add WebSocket support, the base URL will be respected for WebSocket connections as well.

5. **Configuration Files**: The base URL can be set via command line, environment variables, or Flask configuration files.

## Troubleshooting

### Common Issues

**Issue**: GDS loads but resources (CSS/JS) are not loading
**Solution**: Ensure your reverse proxy is correctly forwarding all requests under the base URL path.

**Issue**: API calls are failing
**Solution**: Check that the base URL is correctly configured and that your proxy is forwarding API requests.

**Issue**: Browser opens wrong URL
**Solution**: The GDS automatically opens the browser with the correct URL including the base URL. If this fails, manually navigate to the correct URL.

### Debug Mode

To debug base URL issues, you can check the configuration endpoint:

```bash
curl http://localhost:5000/your-base-url/config
```

This should return JSON with the current base URL configuration.

## Migration from Previous Versions

If you're upgrading from a previous version of F´ GDS:

1. The default behavior (no base URL) remains unchanged
2. No existing configurations need to be modified
3. The new `--base-url` option is completely optional
4. All existing documentation and examples continue to work

## Support

For issues related to the base URL feature, please:

1. Check that your base URL follows the validation rules
2. Verify your reverse proxy configuration
3. Test with a simple base URL first (e.g., `/test`)
4. Check the browser developer console for any JavaScript errors

For additional support, please refer to the main F´ documentation or open an issue on the F´ GitHub repository.
