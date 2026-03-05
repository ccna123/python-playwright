# 1. Base image chính chủ AWS (Amazon Linux 2)
FROM public.ecr.aws/lambda/python:3.9

# 2. Cài dependencies bằng YUM (vì đây là Amazon Linux)
# Cài Pango, Cairo và Font tiếng Nhật (Noto Sans CJK)
RUN yum install -y \
    pango \
    pango-devel \
    cairo \
    cairo-devel \
    libffi-devel \
    google-noto-sans-japanese-fonts \
    && yum clean all

# 3. Cài đặt thư viện Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy code vào đúng thư mục của Lambda
COPY main.py ${LAMBDA_TASK_ROOT}

# 5. Handler phải trùng với tên file và tên hàm (app.py -> def handler)
CMD [ "main.handler" ]