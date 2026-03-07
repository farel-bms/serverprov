import json
import boto3
import psycopg2
import os
import logging
import io
from datetime import datetime, timedelta
from aws_xray_sdk.core import patch_all
import pandas as pd

patch_all()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client('secretsmanager')
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

_db_credentials = None
S3_BUCKET = os.environ.get('S3_LOGS_BUCKET', '')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')


def get_db_credentials():
    global _db_credentials
    if _db_credentials:
        return _db_credentials
    secret_arn = os.environ['SECRET_ARN']
    response = secrets_client.get_secret_value(SecretId=secret_arn)
    _db_credentials = json.loads(response['SecretString'])
    return _db_credentials


def get_db_connection():
    creds = get_db_credentials()
    import time
    for attempt in range(3):
        try:
            return psycopg2.connect(
                host=creds['host'],
                database=creds['dbname'],
                user=creds['username'],
                password=creds['password'],
                connect_timeout=10
            )
        except Exception as e:
            if attempt == 2:
                raise e
            time.sleep(2 ** attempt)


def lambda_handler(event, context):
    logger.info(json.dumps({'action': 'generate_report_start', 'event': str(event)}))

    report_date = datetime.utcnow().strftime('%Y-%m-%d')
    start_date = (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0)
    end_date = datetime.utcnow().replace(hour=23, minute=59, second=59)

    conn = get_db_connection()

    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:

            # Sheet 1: Orders Summary
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT o.order_id, c.name as customer_name, o.status,
                           o.total_amount, o.created_at, o.payment_transaction_id
                    FROM orders o
                    LEFT JOIN customers c ON o.customer_id = c.customer_id
                    WHERE o.created_at BETWEEN %s AND %s AND o.deleted_at IS NULL
                    ORDER BY o.created_at DESC
                """, (start_date, end_date))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                df_orders = pd.DataFrame(rows, columns=cols)
                df_orders.to_excel(writer, sheet_name='Orders Summary', index=False)

            # Sheet 2: Revenue by Status
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT status, COUNT(*) as order_count,
                           COALESCE(SUM(total_amount), 0) as total_revenue
                    FROM orders
                    WHERE created_at BETWEEN %s AND %s AND deleted_at IS NULL
                    GROUP BY status
                """, (start_date, end_date))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                df_revenue = pd.DataFrame(rows, columns=cols)
                df_revenue.to_excel(writer, sheet_name='Revenue by Status', index=False)

            # Sheet 3: Top Products
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.product_id, p.name, p.category,
                           COALESCE(SUM(oi.quantity), 0) as units_sold,
                           COALESCE(SUM(oi.quantity * oi.unit_price), 0) as revenue,
                           p.stock_quantity as current_stock
                    FROM products p
                    LEFT JOIN order_items oi ON p.product_id = oi.product_id
                    LEFT JOIN orders o ON oi.order_id = o.order_id
                        AND o.created_at BETWEEN %s AND %s
                    WHERE p.deleted_at IS NULL
                    GROUP BY p.product_id, p.name, p.category, p.stock_quantity
                    ORDER BY revenue DESC
                """, (start_date, end_date))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                df_products = pd.DataFrame(rows, columns=cols)
                df_products.to_excel(writer, sheet_name='Top Products', index=False)

            # Sheet 4: Customer Activity
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT c.customer_id, c.name, c.email,
                           COUNT(o.order_id) as order_count,
                           COALESCE(SUM(o.total_amount), 0) as total_spent
                    FROM customers c
                    LEFT JOIN orders o ON c.customer_id = o.customer_id
                        AND o.created_at BETWEEN %s AND %s
                        AND o.deleted_at IS NULL
                    GROUP BY c.customer_id, c.name, c.email
                    ORDER BY total_spent DESC
                """, (start_date, end_date))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                df_customers = pd.DataFrame(rows, columns=cols)
                df_customers.to_excel(writer, sheet_name='Customer Activity', index=False)

            # Sheet 5: Daily Stats
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DATE(created_at) as date,
                           COUNT(*) as total_orders,
                           COUNT(CASE WHEN status='completed' THEN 1 END) as completed,
                           COUNT(CASE WHEN status='failed' THEN 1 END) as failed,
                           COALESCE(SUM(CASE WHEN status='completed' THEN total_amount END), 0) as revenue
                    FROM orders
                    WHERE created_at >= NOW() - INTERVAL '30 days' AND deleted_at IS NULL
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                """)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                df_stats = pd.DataFrame(rows, columns=cols)
                df_stats.to_excel(writer, sheet_name='30-Day Trend', index=False)

        # Upload to S3
        output.seek(0)
        s3_key = f"reports/daily-report-{report_date}.xlsx"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=output.getvalue(),
            ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        # Generate presigned URL (24 hours)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': s3_key},
            ExpiresIn=86400
        )

        # Send SNS notification
        if SNS_TOPIC_ARN:
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f'📊 Daily Report Ready - {report_date}',
                Message=f'Your daily report is ready.\n\nDownload: {presigned_url}\n\nThis link expires in 24 hours.'
            )

        logger.info(json.dumps({'action': 'report_generated', 'date': report_date, 's3_key': s3_key}))

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,x-api-key,X-Api-Key',
                'Access-Control-Allow-Methods': 'GET,OPTIONS'
            },
            'body': json.dumps({
                'report_date': report_date,
                's3_key': s3_key,
                'presigned_url': presigned_url
            })
        }

    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        raise e
    finally:
        conn.close()
