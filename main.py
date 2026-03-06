import asyncio
import os
import json
import sys
from datetime import datetime
from bs4 import BeautifulSoup
import boto3
from botocore.exceptions import ClientError
import uuid
from weasyprint import HTML

# Khởi tạo client bên ngoài để tận dụng connection pooling
s3_client = boto3.client('s3')


def _to_text(value, default: str = "") -> str:
    """Convert nullable/mixed values to a safe string for HTML/template usage."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)

def parse_content_to_html(content_html: str) -> str:
    content_html = _to_text(content_html)
    soup = BeautifulSoup(content_html, 'html.parser')
    tags = {'p', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    unused_tags = {'iframe', 'video', 'embed', 'script'}
    order_counter = 0

    for node in soup.find_all():
        if node.name in unused_tags:
            node.decompose()
            continue

        cls = node.get('class', [])
        style = node.get('style', '') or ''
        if node.name in tags: style += "margin: 0; padding: 0;"
        if node.name == 'p': style += "min-height: 18px;"
        if node.name == 'h1': style += "font-size: 32px;"
        if node.name == 'h2': style += "font-size: 24px;"

        if node.name == 'li':
            data_list = node.get('data-list', '')
            if data_list == 'bullet':
                style += "list-style-type: disc;"
            elif data_list == 'ordered':
                order_counter += 1
                node['value'] = str(order_counter)
                style += "list-style-type: decimal; list-style-position: outside;"
            if style.strip(): node['style'] = style.strip()
            if 'data-list' in node.attrs: del node.attrs['data-list']

        if any(c in cls for c in ['ql-align-left', 'ql-align-center', 'ql-align-right', 'ql-align-justify']):
            align = next(c.split('-')[-1] for c in cls if 'ql-align' in c)
            style += f"text-align: {align};"

        if 'ql-size-small' in cls: style += "font-size: 12px;"
        if 'ql-size-large' in cls: style += "font-size: 24px;"
        if 'ql-size-huge' in cls: style += "font-size: 40px; font-weight: bold;"

        for i in range(1, 9):
            if f'ql-indent-{i}' in cls: style += f"padding-left: {3 * i}em;"

        if style.strip(): node['style'] = style.strip()
        if cls: del node['class']

    return str(soup)

def page_html(data: dict) -> str:
    parsed_content = parse_content_to_html(data.get('content'))
    target_all = "公開" if data.get('is_public', False) else "、".join(
        [_to_text(d.get('department_name')) for d in data.get('departments', [])] +
        [_to_text(d.get('division_name')) for d in data.get('divisions', [])] +
        [_to_text(g.get('group_name')) for g in data.get('groups', [])] +
        [_to_text(u.get('user_fullname')) for u in data.get('users', [])]
    )

    return f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Noto Sans JP', 'Helvetica', 'Arial', sans-serif; margin: 0; padding: 20px; font-size: 12pt; line-height: 1.5; }}
            .header-table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
            .header-table th {{ background-color: #d9e9f3; text-align: left; padding: 6px 10px; font-weight: normal; white-space: nowrap; width: 80px; border: 1px solid #ccc; }}
            .header-table td {{ padding: 6px 10px; background-color: #F3F3F3; border: 1px solid #ccc; }}
            .content-title {{ margin-top: 30px; padding: 6px 10px; background-color: #D2E1E7; font-weight: bold; border: 1px solid #ccc; }}
            .content {{ padding: 20px; background-color: #FBFBFB; border: 1px solid #ccc; border-top: none; min-height: 200px; }}
            img {{ max-width: 100%; height: auto; display: block; margin: 10px 0; }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <th>起票者</th><td>{_to_text(data.get('user_fullname'), 'Unknown')}</td>
                <th>起票日</th><td>{data.get('date_obj').strftime("%Y/%m/%d") if data.get('date_obj') else ''}</td>
                <th>タイプ</th><td>{_to_text(data.get('report_type_name'), 'N/A')}</td>
            </tr>
        </table>
        <table class="header-table">
            <tr><th>閲覧者</th><td colspan="5">{target_all}</td></tr>
        </table>
        <div class="content-title">内容</div>
        <div class="content">{parsed_content}</div>
    </body>
    </html>
    """

async def process_logic(body: dict, bucket_name: str):
    """Hàm xử lý chính tách biệt hoàn toàn để dùng chung"""
    report_id = body.get('report_id') or str(uuid.uuid4())
    content_html = _to_text(body.get('content'))
    if not content_html.strip():
        raise ValueError("Content is empty")
    
    # Xử lý date
    raw_date = body.get('date')
    date_obj = datetime.now()
    if raw_date:
        try:
            date_obj = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
        except: pass

    pdf_data = {**body, "date_obj": date_obj}
    html = page_html(pdf_data)
    
    # Generate PDF
    pdf_bytes = HTML(string=html).write_pdf()
    
    # Upload S3
    key = f"app/pdf/report_{report_id}.pdf"
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=pdf_bytes,
            ContentType='application/pdf'
        )
        print(f"S3 upload success: s3://{bucket_name}/{key}")

    except ClientError as e:
        print("S3 Upload Error:", e.response['Error']['Message'])
        raise Exception(f"S3 upload failed: {e.response['Error']['Message']}")

    except Exception as e:
        print("Unexpected S3 Error:", str(e))
        raise Exception(f"S3 upload failed: {str(e)}")


    # Signed URL
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': key},
            ExpiresIn=300
        )
    except ClientError as e:
        print("Presigned URL Error:", e.response['Error']['Message'])
        raise Exception(f"Presigned URL failed: {e.response['Error']['Message']}")

# --- HANDLER CHO LAMBDA (NHẬN REQUEST) ---
def handler(event, context):
    bucket_name = os.environ.get("S3_BUCKET_NAME")
    print(event)
    print("chạy trong handler")

    try:
        # API Gateway
        if isinstance(event, dict) and "body" in event:
            body = event["body"]

            if isinstance(body, str):
                body = json.loads(body)

        # Local Lambda Runtime
        elif isinstance(event, str):
            body = json.loads(event)

        else:
            body = event

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(process_logic(body, bucket_name))

        return {
            "statusCode": 200,
            "body": json.dumps(result)
        }

    except Exception as e:
        print(e)
        return {
            "statusCode": 500,
            "body": str(e)
        }
# --- MAIN CHO LOCAL SCRIPT (CHẠY FILE TRỰC TIẾP) ---
async def main():
    print("--- Chế độ chạy script Local ---")
    bucket_name = os.environ.get("S3_BUCKET_NAME")
    if not bucket_name:
        print("Lỗi: Thiếu S3_BUCKET_NAME env"); return

    try:
        with open("test_data.json", "r") as f:
            message_body = json.load(f)
        res = await process_logic(message_body, bucket_name)
        print(f"Thành công! URL: {res['url']}")
    except FileNotFoundError:
        print("Lỗi: Không tìm thấy test_data.json")

if __name__ == "__main__":
    # Nếu chạy 'python app.py' thì vào main, nếu Docker Lambda gọi thì nó gọi thẳng vào 'handler'
    asyncio.run(main())
