# Sử dụng image Python chính thức
FROM public.ecr.aws/docker/library/python:3.10-slim

# Cài các dependencies hệ thống cần cho Playwright + Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Copy requirements trước để tận dụng cache layer
COPY requirements.txt .

#Cài Playwright
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install playwright && playwright install chromium --with-deps

# Copy toàn bộ source code
COPY . .

# Command chạy ứng dụng
CMD ["python", "main.py"]