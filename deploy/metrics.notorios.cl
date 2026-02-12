server {
    listen 80;
    server_name metrics.notorios.cl;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name metrics.notorios.cl;
    ssl_certificate /etc/ssl/cloudflare/notorios.cl.pem;
    ssl_certificate_key /etc/ssl/cloudflare/notorios.cl.key;

    location / {
        proxy_pass http://127.0.0.1:6972;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
