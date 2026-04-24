# Деплой через GitHub + Render

## 1. Залей на GitHub

1. Создай новый репозиторий на github.com (например `budget-bot`)
2. В папке `budget-bot` открой терминал и выполни:
```
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<твой-юзер>/budget-bot.git
git push -u origin main
```
> `.env` не попадёт в гит — он в `.gitignore`

---

## 2. Задеплой на Render

1. Зайди на https://render.com → New → **Web Service**
2. Connect GitHub → выбери репозиторий `budget-bot`
3. Настройки:
   - **Environment:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Листай вниз → **Environment Variables** → добавь:
   ```
   BOT_TOKEN = 8671767489:AAGyK62T_1_nf6HfrcFccV1N6Eu4Gcrowtc
   WEBAPP_URL = https://<твой-сервис>.onrender.com
   ```
   WEBAPP_URL узнаешь после деплоя — Render покажет домен вида `https://budget-bot-xxxx.onrender.com`
5. Нажми **Create Web Service** → ждёшь ~2 минуты

---

## 3. Впиши WEBAPP_URL

После деплоя Render даст тебе домен. Вернись в Environment Variables и обнови:
```
WEBAPP_URL = https://budget-bot-xxxx.onrender.com
```
Затем нажми **Manual Deploy → Deploy latest commit**.

---

## 4. Зарегистрируй webhook (один раз)

На своём компе в папке `budget-bot`:
```
pip install -r requirements.txt
python setup_webhook.py
```

---

## 5. Зарегистрируй Mini App у @BotFather

1. `/newapp` → выбери своего бота
2. Название: `Мой бюджет`
3. URL: `https://budget-bot-xxxx.onrender.com`
4. Готово

Теперь `/start` в боте покажет кнопку → открывает мини-апп → данные пишутся в базу и не сбрасываются.

---

## ⚠️ Важно про бесплатный Render

Бесплатный план засыпает после 15 минут неактивности.
При первом открытии после паузы будет ~30 секунд задержки.
Чтобы этого не было — подключи Render Cron Job или UptimeRobot (бесплатный пинг каждые 10 мин).
