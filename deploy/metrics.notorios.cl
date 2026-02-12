# Managed by Certbot on the VM — this file is kept as reference.
# Actual live config is at /etc/nginx/sites-enabled/metrics.notorios.cl
#
# SSL via Let's Encrypt (auto-renewed by certbot timer).
# Initial setup: sudo certbot --nginx -d metrics.notorios.cl

server {
    server_name metrics.notorios.cl;

    location / {
        proxy_pass http://127.0.0.1:6972;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/metrics.notorios.cl/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/metrics.notorios.cl/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = metrics.notorios.cl) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    server_name metrics.notorios.cl;
    return 404; # managed by Certbot
}
