import asyncio
import os
import json
import time
import sys
from datetime import datetime
from bs4 import BeautifulSoup
import boto3
from botocore.exceptions import ClientError
import uuid
from weasyprint import HTML

# ─── Hàm parse rich text giống C# ───
def parse_content_to_html(content_html: str) -> str:
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

        if node.name in tags:
            style += "margin: 0; padding: 0;"

        if node.name == 'p':
            style += "min-height: 18px;"

        if node.name == 'h1':
            style += "font-size: 32px;"
        if node.name == 'h2':
            style += "font-size: 24px;"

        if node.name == 'li':
            data_list = node.get('data-list', '')
            if data_list == 'bullet':
                style += "list-style-type: disc;"
            elif data_list == 'ordered':
                order_counter += 1
                node['value'] = str(order_counter)
                style += "list-style-type: decimal; list-style-position: outside;"
            if style.strip():
                node['style'] = style.strip()
            if 'data-list' in node.attrs:
                del node.attrs['data-list']

        # Align
        if any(c in cls for c in ['ql-align-left', 'ql-align-center', 'ql-align-right', 'ql-align-justify']):
            align = 'left' if 'ql-align-left' in cls else \
                    'center' if 'ql-align-center' in cls else \
                    'right' if 'ql-align-right' in cls else 'justify'
            style += f"text-align: {align};"

        # Size
        if 'ql-size-small' in cls:
            style += "font-size: 12px;"
        if 'ql-size-large' in cls:
            style += "font-size: 24px;"
        if 'ql-size-huge' in cls:
            style += "font-size: 40px; font-weight: bold;"

        # Indent
        for i in range(1, 9):
            if f'ql-indent-{i}' in cls:
                style += f"padding-left: {3 * i}em;"

        if style.strip():
            node['style'] = style.strip()

        if cls:
            del node['class']

    return str(soup)

# ─── Tạo HTML giống hệt C# ───
def page_html(data: dict) -> str:
    parsed_content = parse_content_to_html(data['content'])

    target_all = "公開" if data.get('is_public', False) else "、".join(
        [d.get('department_name', '') for d in data.get('departments', [])] +
        [d.get('division_name', '') for d in data.get('divisions', [])] +
        [g.get('group_name', '') for g in data.get('groups', [])] +
        [u.get('user_fullname', '') for u in data.get('users', [])]
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: 'Noto Sans JP', 'Helvetica', 'Arial', sans-serif;
                margin: 0;
                padding: 0;
                font-size: 12pt;
                line-height: 1.5;
            }}
            .header-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 10px;
            }}
            .header-table th {{
                background-color: #d9e9f3;
                text-align: left;
                padding: 6px 10px;
                font-weight: normal;
                white-space: nowrap;
                width: 80px;
            }}
            .header-table td {{
                padding: 6px 10px;
                background-color: #F3F3F3;
            }}
            .content-title {{
                margin-top: 30px;
                padding: 6px 10px;
                background-color: #D2E1E7;
                font-weight: bold;
            }}
            .content {{
                padding: 20px;
                background-color: #FBFBFB;
                border: 1px solid #BFBFBF;
                border-top: none;
                min-height: 200px;
            }}
            img {{
                max-width: 100%;
                height: auto;
                display: block;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <th>起票者</th><td>{data.get('user_fullname', 'Unknown')}</td>
                <th>起票日</th><td>{data.get('date', datetime.now()).strftime("%Y/%m/%d")}</td>
                <th>タイプ</th><td>{data.get('report_type_name', 'N/A')}</td>
            </tr>
        </table>
        <table class="header-table">
            <tr>
                <th>閲覧者</th>
                <td colspan="5">{target_all}</td>
            </tr>
        </table>
        <div class="content-title">内容</div>
        <div class="content">
            {parsed_content}
        </div>
    </body>
    </html>
    """
    return html

async def generate_pdf_from_html(html_content: str) -> bytes:
    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes
    except Exception as e:
        print(f"Lỗi generate PDF bằng WeasyPrint: {e}")
        raise


async def upload_to_s3_and_get_signed_url(pdf_bytes: bytes, bucket_name: str, report_id: str) -> str:
    s3_client = boto3.client('s3')
    
    today = datetime.now().strftime("%Y/%m")
    key = f"app/pdf/report_{report_id}.pdf"
    
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=pdf_bytes,
            ContentType='application/pdf'
        )
        
        signed_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': key},
            ExpiresIn=300  # 5 phút
        )
        return signed_url
    
    except ClientError as e:
        print(f"Lỗi khi upload lên S3: {e}")
        raise

async def process_message(message_body: dict, bucket_name: str, dynamodb_client, table_name: str):
    try:
        body = json.loads(message_body)
        
        # Lấy các trường cần thiết từ message SQS
        report_id = body.get('report_id') or str(uuid.uuid4())  # fallback nếu không có id
        content_html = body.get('content', '')
        
        if not content_html.strip():
            print(f"Message {message_body} thiếu content → bỏ qua")
            return

        # Lấy session_id từ message (backend phải gửi kèm)
        session_id = body.get('session_id')
        if not session_id:
            print(f"Message thiếu session_id → không thể cập nhật DynamoDB")
            # Vẫn xử lý PDF nhưng không update DB

        print(f"Xử lý report ID: {report_id}")

        # Tạo data cho PDF từ chính message SQS
        pdf_data = {
            "title": body.get('title', "Báo cáo"),
            "content": content_html,                    # ← nội dung chính từ SQS
            "date": datetime.fromisoformat(body.get('date', datetime.now().isoformat())),
            "is_public": body.get('is_public', True),
            "report_type_name": body.get('report_type_name', 'N/A'),
            "user_fullname": body.get('user_fullname', 'Unknown'),
            "departments": body.get('departments', []),
            "divisions": body.get('divisions', []),
            "groups": body.get('groups', []),
            "users": body.get('users', []),
        }

        # Generate HTML và PDF
        html = page_html(pdf_data)
        pdf_bytes = await generate_pdf_from_html(html)

        # Upload S3 và lấy signed URL
        signed_url = await upload_to_s3_and_get_signed_url(pdf_bytes, bucket_name, report_id)

        print(f"Hoàn tất report {report_id}")
        print(f"SIGNED URL: {signed_url}")

        # # Lưu file local để debug (có thể bỏ sau)
        # local_path = f"/app/output/report_{report_id}.pdf"
        # with open(local_path, "wb") as f:
        #     f.write(pdf_bytes)
        # print(f"Đã lưu file local: {local_path}")

        # Cập nhật DynamoDB nếu có session_id
        if session_id:
            update_report_status(dynamodb_client, table_name, session_id, signed_url)

    except json.JSONDecodeError:
        print(f"Message {message_body.get('MessageId', 'unknown')} không phải JSON hợp lệ → bỏ qua")
        if session_id:
            update_report_status(dynamodb_client, table_name, session_id, "", error_reason="Invalid JSON", status="failed")
    except Exception as e:
        print(f"Lỗi xử lý message {message_body.get('MessageId', 'unknown')}: {e}")
        if session_id:
            update_report_status(dynamodb_client, table_name, session_id, "", error_reason=str(e), status="failed")

        # Không delete để SQS retry

# ─── Update trạng thái DynamoDB khi hoàn thành ───
def update_report_status(dynamodb_client, table_name: str, session_id: str, signed_url: str, error_reason: str = "", status: str = "complete"):
    try:
        dynamodb_client.update_item(
            TableName=table_name,
            Key={'session_id': {'S': session_id}},
            UpdateExpression="SET #status = :status, #url = :url, #error_reason = :error_reason, updated_at = :updated_at",
            ExpressionAttributeNames={
                "#status": "status",
                "#url": "url",
                "#error_reason": "error_reason"
            },
            ExpressionAttributeValues={
                ":status": {"S": status},
                ":url": {"S": signed_url},
                ":error_reason": {"S": error_reason},
                ":updated_at": {"S": datetime.utcnow().isoformat()}
            },
            ReturnValues="UPDATED_NEW"
        )
        print(f"Đã cập nhật DynamoDB: session_id={session_id}, status={status}, url={signed_url}")
    except ClientError as e:
        print(f"Lỗi cập nhật DynamoDB cho session {session_id}: {e}")

async def main():
    print("===========================================================")
    print("Worker bắt đầu xử lý từ environment variables...")
    
    env = os.environ.get("ENV", "local")
    bucket_name = os.environ.get("S3_BUCKET_NAME")
    dynamodb_table = os.environ.get("DYNAMODB_TABLE_NAME", "ReportDownloadStatus")  # default tên table

    if not bucket_name:
        print("Thiếu S3_BUCKET_NAME")
        sys.exit(1)

    # Lấy message body từ environment variable (truyền từ Lambda)
    if env == "local":
        # Dành cho local testing: đọc từ file sample_message.json
        try:
            with open("test_data.json", "r") as f:
                message_body = f.read()
        except FileNotFoundError:
            print("File test_data.json không tồn tại. Vui lòng tạo file này với nội dung JSON mẫu để test local.")
            sys.exit(1)
    else:
        message_body = os.environ.get("MESSAGE_BODY")
        
    if not message_body:
        print("Thiếu MESSAGE_BODY từ environment variables")
        sys.exit(1)

    dynamodb_client = boto3.client('dynamodb')

    print(f"Bucket: {bucket_name}")
    print(f"DynamoDB Table: {dynamodb_table}")
    print(f"Message Body received: {message_body[:100]}...")  # in ngắn để debug

    await process_message(message_body, bucket_name, dynamodb_client, dynamodb_table)

    print("Worker hoàn thành xử lý message duy nhất.")
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())