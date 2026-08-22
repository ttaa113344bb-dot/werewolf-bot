FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# قاعدة البيانات SQLite تُخزَّن هنا افتراضيًا؛ اربط هذا المسار بوحدة تخزين (volume) دائمة عند النشر
ENV DATABASE_PATH=/app/data/game.db
RUN mkdir -p /app/data

CMD ["python", "app.py"]
