# 🔄 Пересоздание интеграции AmoCRM с правильными правами

## Шаг 1: Создать новую интеграцию

1. Откройте: https://sovanidirektor.amocrm.ru/settings/integrations/

2. Нажмите **"Создать интеграцию"**

3. Заполните:
   - **Название:** `SalesBot MVP v2`
   - **Redirect URI:** `https://app.justbusiness.lol/auth/callback`

4. **ОБЯЗАТЕЛЬНО выберите права доступа:**
   
   ```
   ☑️ Пользователи (Users)
   ☑️ Сделки (Leads)  
   ☑️ Контакты (Contacts)
   ☑️ Звонки (Calls) ← ВАЖНО!!!
   ☑️ Задачи (Tasks)
   ☑️ Примечания (Notes)
   ☑️ Файлы (Files)
   ```

5. Сохраните и скопируйте:
   - ✅ Client ID
   - ✅ Client Secret

---

## Шаг 2: Получить код авторизации

1. Замените YOUR_NEW_CLIENT_ID на ваш новый Client ID:

```
https://sovanidirektor.amocrm.ru/oauth?client_id=YOUR_NEW_CLIENT_ID&state=123456&mode=post_message
```

2. Откройте эту ссылку в браузере

3. Нажмите **"Разрешить"**

4. Скопируйте код из URL (параметр `code=...`)

---

## Шаг 3: Обменять код на токены

Выполните на сервере:

```bash
curl -X POST "https://sovanidirektor.amocrm.ru/oauth2/access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_NEW_CLIENT_ID",
    "client_secret": "YOUR_NEW_CLIENT_SECRET",
    "grant_type": "authorization_code",
    "code": "YOUR_AUTHORIZATION_CODE",
    "redirect_uri": "https://app.justbusiness.lol/auth/callback"
  }'
```

Скопируйте из ответа:
- access_token
- refresh_token

---

## Шаг 4: Обновить .env файл

```bash
nano /root/salesbot-mvp/.env
```

Замените:
- AMOCRM_CLIENT_ID=новый_client_id
- AMOCRM_CLIENT_SECRET=новый_client_secret  
- AMOCRM_ACCESS_TOKEN=новый_access_token
- AMOCRM_REFRESH_TOKEN=новый_refresh_token

---

## Шаг 5: Перезапустить сервис

```bash
systemctl restart salesbot-api
systemctl status salesbot-api
```

---

## Шаг 6: Проверить доступ к звонкам

```bash
curl -s "https://app.justbusiness.lol/health" | jq '.checks.amocrm'
```

Должно быть: `"status": "healthy"`

---

## Шаг 7: Настроить webhook (еще раз)

В новой интеграции:
- URL: `https://app.justbusiness.lol/webhook/amocrm/call`
- События: Звонок создан, Звонок обновлен

---

✅ Готово! Теперь интеграция имеет доступ к звонкам!
