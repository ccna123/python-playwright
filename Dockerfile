# Sử dụng image Python chính thức
FROM python:3.11-slim

# Cài các dependencies hệ thống cần cho Playwright + Chromium
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    fonts-noto-cjk \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Copy requirements trước để tận dụng cache layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cài Playwright và các browser cần thiết
RUN pip install playwright && playwright install chromium --with-deps

# Copy toàn bộ source code
COPY . .

# Tạo thư mục để lưu PDF (sẽ mount volume vào đây)
# RUN mkdir -p /app/output

# Command chạy ứng dụng
# Ví dụ chạy file test của bạn
CMD ["python", "main.py"]
# Hoặc nếu bạn có file chính khác, thay bằng tên file đó
# CMD ["python", "main.py"]