# Guia de Implantação e Migração — SMS & MMS Gateway v3.0

Este guia descreve o passo a passo para colocar a versão **3.0** em produção com **Nginx HTTPS**, **systemd**, **Pixel 6** e migração segura do banco existente (`sms_gateway_1937.db`).

---

## 1. Configuração do Nginx (HTTPS + SSE sem buffering)

No bloco `server` HTTPS do Nginx, configure o proxy para o Uvicorn local (`127.0.0.1:8000`) com atenção especial ao endpoint `/events` (SSE) e ao tamanho máximo de anexos MMS:

```nginx
server {
    listen 443 ssl http2;
    server_name sms.clinic.internal;

    ssl_certificate     /etc/ssl/clinic/sms.crt;
    ssl_certificate_key /etc/ssl/clinic/sms.key;

    client_max_body_size 25M;

    # Repassa IP real para os audit_logs do sistema
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Stream em tempo real (SSE) — buffering precisa estar desligado
    location /events {
        proxy_pass http://127.0.0.1:8000/events;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        chunked_transfer_encoding off;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
    }
}
```

> **Dica:** Enquanto os certificados HTTPS ainda estiverem sendo finalizados, defina `SESSION_COOKIE_SECURE=false` no `.env`. Assim que o HTTPS estiver ativo, mude para `SESSION_COOKIE_SECURE=true` e reinicie o serviço.

---

## 2. Serviço systemd (1 worker obrigatório)

```ini
[Unit]
Description=SMS & MMS Gateway v3.0
After=network.target

[Service]
User=smsuser
WorkingDirectory=/var/www/sms-gateway
ExecStart=/var/www/sms-gateway/start_app.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

## 3. Migração Segura do Banco de Produção (`sms_gateway_1937.db`)

O script de migração **não altera** o banco antigo (`sms_gateway_1937.db`). Ele cria um backup antes, gera um novo banco limpo (`data/sms_gateway_v3.db`) e copia os anexos MMS para a pasta privada (`data/media/`).

1. **Parar o serviço v2** para garantir que nenhuma mensagem nova chegue durante a cópia:
   ```bash
   sudo systemctl stop sms-gateway
   ```

2. **Simulação (`--dry-run`)** — apenas analisa os dados e mostra o relatório sem gravar nada:
   ```bash
   python3 scripts/migrate_v2_to_v3.py \
     --source /var/www/sms-gateway/sms_gateway_1937.db \
     --target /var/www/sms-gateway/data/sms_gateway_v3.db \
     --source-media /var/www/sms-gateway/static/media \
     --target-media /var/www/sms-gateway/data/media \
     --dry-run
   ```

3. **Execução real da migração:**
   ```bash
   python3 scripts/migrate_v2_to_v3.py \
     --source /var/www/sms-gateway/sms_gateway_1937.db \
     --target /var/www/sms-gateway/data/sms_gateway_v3.db \
     --source-media /var/www/sms-gateway/static/media \
     --target-media /var/www/sms-gateway/data/media \
     --backup-dir /var/www/sms-gateway/backups
   ```
   Verifique no relatório final que `SQLite integrity: ok`, `Foreign key errors: 0` e `Audit chain valid: True`.

4. **Criar as contas de usuário (Médico e Lori):**
   ```bash
   python3 scripts/manage_users.py create-admin --username doctor --display-name "Dr. Smith"
   python3 scripts/manage_users.py create-user --username lori --display-name "Lori" --role staff
   ```
   *(Senhas devem ter pelo menos 12 caracteres.)*

5. **Subir a v3.0:**
   ```bash
   sudo systemctl start sms-gateway
   ```

6. **Plano de Rollback:** Como o banco `sms_gateway_1937.db` e a pasta `static/media/` originais permanecem intactos, caso precise voltar à v2 basta voltar para o código v2 e reiniciar o serviço.

---

## 4. Ativando Assinatura HMAC-SHA256 no Pixel 6

1. No app **SMS Gateway for Android** no Pixel 6, acesse **Settings → Webhooks → Signing Key** e defina uma chave secreta forte.
2. No arquivo `.env` do servidor, configure:
   ```env
   WEBHOOK_VERIFY_SIGNATURE=true
   WEBHOOK_SIGNING_KEY=<mesma_chave_do_pixel6>
   ```
3. Reinicie o serviço (`sudo systemctl restart sms-gateway`).
